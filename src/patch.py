from libero.libero.envs.predicates import register_predicate_fn
from libero.libero.envs.predicates.base_predicates import *
from libero.libero.envs.object_states import BaseObjectState, SiteObjectState
from libero.libero.envs.objects import ArticulatedObject
from src.extract_xml import locate_libero_xml, find_geoms_for_site
import numpy as np
import re

def split_object_name(object_name, parent_name):
    # Extract the prefix and the remaining part
    match = re.match(r"(.*)_\d+", parent_name)
    if match:
        prefix = match.group(1)  # Everything before '_<digit>'
        # Remove the parent_name from full_string to get the suffix
        suffix = object_name[len(parent_name) + 1:]  # +1 for the underscore
        return prefix, suffix
    else:
        raise ValueError(f"parent name '{parent_name}' is not in the expected format.")

def get_list_of_geom_names_for_site(object_name, parent_name, env):
    list_of_geom_names = []
    target_object_name, target_site_name = split_object_name(object_name, parent_name)
    path = locate_libero_xml(target_object_name)
    site_geom_positions = find_geoms_for_site(path, target_site_name)
    for geom_name in env.sim.model.geom_names:
        if geom_name is None:
            continue
        if parent_name in geom_name:  # Filter for object-specific geoms
            geom_id = env.sim.model.geom_name2id(geom_name)
            geom_position = env.sim.model.geom_pos[geom_id]
            for site_geom_pos in site_geom_positions:
                if (site_geom_pos == geom_position).all():
                    list_of_geom_names.append(geom_name)
    return list_of_geom_names

def check_gripper_contact(self):
    # object could be an object (articulated, hop) or a site
    # sites do not have a way to dynamically get geoms/check contact
    target_object_geoms = self.env.get_object(self.object_name).contact_geoms
    gripper_geoms = ["gripper0_finger1_pad_collision", "gripper0_finger2_pad_collision"]
    if self.object_state_type == "site":
        list_of_geom_names = get_list_of_geom_names_for_site(self.object_name, self.parent_name, self.env)
        return self.env.check_contact(gripper_geoms, list_of_geom_names)
    else:
        return self.env.check_contact(gripper_geoms, target_object_geoms)

BaseObjectState.check_gripper_contact = check_gripper_contact


def check_grasp(self):
    target_object_geoms = self.env.get_object(self.object_name).contact_geoms # .contact_geoms is not really necessary, but added for readibility
    gripper_geoms = ["gripper0_finger1_pad_collision", "gripper0_finger2_pad_collision"] # or gripper_geoms = self.env.robots[0].gripper
    if self.object_state_type == "site":
        list_of_geom_names = get_list_of_geom_names_for_site(self.object_name, self.parent_name, self.env)
        return self.env._check_grasp(gripper=gripper_geoms, object_geoms=list_of_geom_names)
    else:
        return self.env._check_grasp(gripper=gripper_geoms, object_geoms=target_object_geoms)

BaseObjectState.check_grasp = check_grasp


@register_predicate_fn
class Contact(UnaryAtomic):
    def __call__(self, arg):
        return arg.check_gripper_contact()


@register_predicate_fn
class Grasp(UnaryAtomic):
    def __call__(self, arg):
        return arg.check_grasp()


@register_predicate_fn
class Reach(MultiarayAtomic):
    """
    Reach within a given distance away from the given object, or within the bounds of the object.
    If the given object is a site, the gripper going into the bounds of the site automatically counts as a success.
    """
    def __call__(self, *args):
        assert len(args) >= 1
        if len(args) == 1:
            return self.reach(args[0])
        else:
            goal_distance = float(args[1])
            return self.reach(args[0], goal_distance)
        

    def reach(self, object_state: BaseObjectState, goal_distance: float = None):
        env = object_state.env
        grip_site_pos = env.sim.data.get_site_xpos("gripper0_grip_site") # This is the position between the 2 claws

        object_pos = object_state.get_geom_state()['pos']
        dist = np.linalg.norm(grip_site_pos - object_pos)
        # print(dist)

        # Check whether object has been reached (without caring about goal_distance)
        if isinstance(object_state, SiteObjectState):
            object_mat = env.sim.data.get_site_xmat(object_state.object_name)
            object_site = env.get_object_site(object_state.object_name)
            if object_site.in_box(object_pos, object_mat, grip_site_pos):
                return True
        elif dist < 0.02: # if not a site, just use distance. There should be an in_box for regular objects, but for now we just have this
            return True
        
        # If object has not been reached, check if goal distance is reached
        return dist < goal_distance



@register_predicate_fn
class PartialOpen(MultiarayAtomic):
    """
    Open an articulated object by a given fraction.
    The bounds for fully open/closed is given by the object_properties of the articulated object
    """
    def __call__(self, *args):
        assert len(args) >= 2
        open_amount = float(args[1])
        return self.is_partial_open(args[0], open_amount)
    
    def is_articulated_object_partial_open(self, object: ArticulatedObject, qpos, open_amount):
        "Checks whether the object is open by the given open_amount in range [0, 1]"

        default_open_ranges = object.object_properties["articulation"]["default_open_ranges"]
        default_close_ranges = object.object_properties["articulation"]["default_close_ranges"]

        # if no ranges provided, just assume it is closed
        if len(default_open_ranges) == 0 or len(default_close_ranges) == 0:
            return False
        
        # the ranges provide a leeway. depending on which is smaller, we choose the innermost side of the leeway
        if default_open_ranges[0] < default_close_ranges[0]:
            fully_open = max(default_open_ranges)
            fully_closed = min(default_close_ranges)
        else:
            fully_open = min(default_open_ranges)
            fully_closed = max(default_close_ranges)

        # to count as partial open, qpos must be on the fully open side of the threshold
        threshold = open_amount * fully_open + (1-open_amount) * fully_closed
        if fully_open < fully_closed:
            return qpos < threshold
        else:
            return qpos > threshold

    def is_partial_open(self, object_state: BaseObjectState, open_amount: float):
        "Checks whether any joint is open by open_amounts"
        env = object_state.env
        for joint in env.get_object_site(object_state.object_name).joints:
            qpos = env.sim.data.get_joint_qpos(joint)
            object = env.get_object(object_state.parent_name)

            assert isinstance(object, ArticulatedObject), (
                f"{object_state.object_name}'s parent, {object_state.parent_name} "
                "is not an articulated object. PartialOpen can only be used with articulated objects"
            )
            if self.is_articulated_object_partial_open(object, qpos, open_amount):
                return True
            
        return False



@register_predicate_fn
class PartialClose(MultiarayAtomic):
    """
    Close an articulated object by a given fraction.
    The bounds for fully open/closed is given by the object_properties of the articulated object
    """
    def __call__(self, *args):
        assert len(args) >= 2
        close_amount = float(args[1])
        # partial close is just the opposite of partial open, but with the parameter flipped
        return not PartialOpen()(args[0], 1-close_amount, *args[2:])