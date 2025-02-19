from libero.libero.envs.predicates import VALIDATE_PREDICATE_FN_DICT, UnaryAtomic, BinaryAtomic, MultiarayAtomic
from libero.libero.envs.object_states import BaseObjectState, ObjectState, SiteObjectState
from libero.libero.envs.objects import ArticulatedObject
from robosuite.models.objects import MujocoXMLObject
import numpy as np
from typing import Optional

from ..libero_utils import check_contact_excluding_gripper, compute_bounding_box_from_geoms


def register_predicate_fn(target_class):
    """We design the mapping to be case-INsensitive."""
    VALIDATE_PREDICATE_FN_DICT[target_class.__name__.lower()] = target_class()
    # print("Registered new predicate", target_class.__name__.lower())
    return target_class


@register_predicate_fn
class Contact(UnaryAtomic):
    def __call__(self, arg: BaseObjectState):
        return arg.check_gripper_contact()


@register_predicate_fn
class Grasp(UnaryAtomic):
    def __call__(self, arg: BaseObjectState):
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
        

    def reach(self, object_state: BaseObjectState, goal_distance: float = 0):
        goal_distance = max(goal_distance, 0.01) # Have some leeway for goal distance
        
        env = object_state.env
        grip_site_pos: np.ndarray = env.sim.data.get_site_xpos("gripper0_grip_site") # This is the position between the 2 claws

        object_pos = object_state.get_geom_state()['pos']
        dist = np.linalg.norm(grip_site_pos - object_pos)

        # Check whether the object has been reached based on whether geoms bounding box
        min_bounds, max_bounds = compute_bounding_box_from_geoms(env.sim, object_state.get_geoms())
        if (grip_site_pos > min_bounds).all() and (grip_site_pos < max_bounds).all():
            return True

        # replaced below with the geom bounding box solution above
        # # Check whether object has been reached (without caring about goal_distance)
        # # TODO: there is a check_contain in ObjectState, but that takes in another object as a parameter, not a single point
        # # Maybe add a new function in BaseObjectState to check whether a point is in the object
        # # Also, these in_box functions approximate the objects as axis-aligned
        # if isinstance(object_state, ObjectState):
        #     object: MujocoXMLObject = env.get_object(object_state.object_name)
        #     return object.in_box(object_pos, grip_site_pos) # FIXME: this doesn't work.
        # elif isinstance(object_state, SiteObjectState):
        #     object_mat = env.sim.data.get_site_xmat(object_state.object_name)
        #     object_site = env.get_object(object_state.object_name)
        #     if object_site.in_box(object_pos, object_mat, grip_site_pos):
        #         return True
        
        # If object has not been reached, check if goal distance is reached
        return dist < goal_distance


@register_predicate_fn
class Open(MultiarayAtomic):
    """
    Open an articulated object by a given fraction.
    The bounds for fully open/closed is given by the object_properties of the articulated object
    """
    def __call__(self, *args):
        assert len(args) >= 1
        if len(args) == 1:
            open_amount = 1
        else:
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
        for joint in env.get_object(object_state.object_name).joints:
            qpos = env.sim.data.get_joint_qpos(joint)
            object = env.get_object(object_state.parent_name)

            assert isinstance(object, ArticulatedObject), (
                f"{object_state.object_name}'s parent, {object_state.parent_name} "
                "is not an articulated object. Open can only be used with articulated objects"
            )
            if self.is_articulated_object_partial_open(object, qpos, open_amount):
                return True
            
        return False


@register_predicate_fn
class Close(MultiarayAtomic):
    """
    Close an articulated object by a given fraction.
    The bounds for fully open/closed is given by the object_properties of the articulated object
    """
    def __call__(self, *args):
        assert len(args) >= 1
        if len(args) == 1:
            close_amount = 1
        else:
            close_amount = float(args[1])
        close_amount = float(args[1])
        # partial close is just the opposite of partial open, but with the parameter flipped
        return not Open()(args[0], 1-close_amount, *args[2:])
    

@register_predicate_fn
class Lift(MultiarayAtomic):
    """
    Lift an object by a given distance
    """
    def __call__(self, *args):
        assert len(args) >= 1
        if len(args) == 1:
            return self.is_lifted(args[0])
        elif len(args) == 2:
            if isinstance(args[1], BaseObjectState):
                return self.is_lifted(args[0], other_object_state=args[1])
            else:
                return self.is_lifted(args[0], lift_distance=float(args[1]))
        else:
            return self.is_lifted(args[0], other_object_state=args[1], lift_distance=float(args[2]))
    
    def is_lifted(
        self, 
        object_state: BaseObjectState, 
        other_object_state: Optional[BaseObjectState] = None, 
        lift_distance: float = 0
    ):
        lift_distance = max(lift_distance, 0.01) # <1cm counts as not lifted
        env = object_state.env

        # if the object is contacting another object (eg the table), we don't count it as lifted
        if check_contact_excluding_gripper(env.sim, object_state.object_name):
            return False
        
        # gripper must be touching. This prevents the predicate from being satisfied at the beginning when objects are initialized in the air
        if not object_state.check_gripper_contact():
            return False
        
        min_bounds, _ = compute_bounding_box_from_geoms(env.sim, object_state.get_geoms())
        min_elevation = min_bounds[2]

        if other_object_state is not None:
            _, other_max_bounds = compute_bounding_box_from_geoms(env.sim, other_object_state.get_geoms())
            other_max_elevation = other_max_bounds[2]
        else:
            # TODO: the table isn't always at this level. maybe update this to match the table level. env has a property "z_offset" that could be used
            other_max_elevation = env.workspace_offset[2]
        
        # total_size = np.abs(object_mat @ object_pos)
        # print(object_state, total_size)
        # print(env.sim.model._body_name2id)
        # print(env.sim.model._site_name2id)
        # print(env.sim.data.get_body_xpos("world"))
        # print(env.sim.data.get_body_xpos("floor"))
        # print(env.sim.data.get_body_xpos("living_room_table"))
        # print(env.sim.data.get_body_xpos("living_room_table_col"))
        # print(env.sim.data.get_site_xpos("living_room_table_ketchup_init_region"))
        # print(object_pos)
        # print(min_elevation, other_max_elevation)
        
        return min_elevation - other_max_elevation > lift_distance


@register_predicate_fn
class Align(BinaryAtomic):
    def __call__(self, arg1, arg2):
        return arg2.align(arg1)
    

@register_predicate_fn
class PlaceIn(BinaryAtomic):
    def __call__(self, arg1, arg2):
        return arg2.check_contact(arg1) and arg2.check_contain(arg1) and (not arg1.check_gripper_contact())
    

@register_predicate_fn
class Reset(UnaryAtomic):
    def __call__(self, arg):
        return arg.reset_qpos()