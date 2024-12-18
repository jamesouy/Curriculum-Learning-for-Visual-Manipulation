from libero.libero.envs.predicates import *
from libero.libero.envs.object_states import BaseObjectState, SiteObjectState, ObjectState
from libero.libero.envs.bddl_base_domain import BDDLBaseDomain
from libero.libero.envs.objects import articulated_objects
import numpy as np
from libero.libero.envs.objects import SiteObject

from robosuite.utils.binding_utils import MjSim

def reward(self, action=None):
    """
    Reward function for the task.

    Sparse un-normalized reward:

        - a discrete reward of 1.0 is provided if the task succeeds.

    Args:
        action (np.array): [NOT USED]

    Returns:
        float: reward value
    """
    reward = 0.0

    # define our shaping rewards
    # goal_state = self.parsed_problem["goal_state"]
    # for state in goal_state:
    #     if "reach" in state:
    #         return eval_predicate_fn(state[0], self.object_states_dict[state[1]])

    # sparse completion reward
    if self._check_success():
        reward = 1.0

    # Scale reward if requested
    if self.reward_scale is not None:
        reward *= self.reward_scale / 1.0

    return reward

def is_in_contact(self, other):
    gripper_geoms = ["gripper0_finger1_pad_collision",
    "gripper0_finger2_pad_collision"]
    geom_names = [
        "wooden_cabinet_1_g40",
        "wooden_cabinet_1_g41",
        "wooden_cabinet_1_g42"
    ]
    # Check for contact between gripper and object
    return self.env.check_contact(gripper_geoms, geom_names)

def check_grasp(self, other):
    gripper_geoms = ["gripper0_finger1_pad_collision",
    "gripper0_finger2_pad_collision"]
    geom_names = [
        "ketchup_1_main", 
    ]
    return self.env._check_grasp(gripper=self.env.robots[0].gripper, object_geoms=geom_names)

def reach(self: BaseObjectState, goal_distance: float = None):
    # if "ketchup_1" in self.env.obj_of_interest:
    #     body_main = "ketchup_1_main"
    # else:
    #     body_main = "wooden_cabinet_1_cabinet_top" # it seems like initial object_pos does not change depending on this name, but it does follow the specific drawer

    sim: MjSim = self.env.sim
    gripper_site_pos = sim.data.get_site_xpos("gripper0_grip_site")

    object_pos = self.get_geom_state()['pos']
    dist = np.linalg.norm(gripper_site_pos - object_pos)
    # print("dist:", np.linalg.norm(gripper_site_pos - object_pos))

    # Check whether object has been reached (without caring about goal_distance)
    if isinstance(self, SiteObjectState):
        object_mat = sim.data.get_site_xmat(self.object_name)
        object: SiteObject = self.env.get_object(self.object_name)
        if object.in_box(object_pos, object_mat, gripper_site_pos):
            return True
    elif dist < 0.02: # if not a site, just use distance. There should be an in_box for regular objects, but for now we just have this
        return True
    
    # If object has not been reached, check if goal distance is reached
    return dist < goal_distance

class Contact(UnaryAtomic):
    def __call__(self, arg):
        return arg.is_in_contact(arg)

class Grasp(UnaryAtomic):
    def __call__(self, arg):
        return arg.check_grasp(arg)

class Reach(MultiarayAtomic):
    def __call__(self, *args):
        assert len(args) >= 1
        if len(args) == 1:
            return args[0].reach()
        else:
            goal_distance = float(args[1])
            return args[0].reach(goal_distance)


VALIDATE_PREDICATE_FN_DICT["contact"] = Contact()
VALIDATE_PREDICATE_FN_DICT["grasp"] = Grasp()
VALIDATE_PREDICATE_FN_DICT["reach"] = Reach()

BaseObjectState.is_in_contact = is_in_contact
BaseObjectState.check_grasp = check_grasp
BaseObjectState.reach = reach

# BDDLBaseDomain.reward = reward



# Patches for Cabinet partial open
def wooden_cabinet_is_partial_open(self, qpos, open_amount):
    "Checks whether the cabinet is open by the given open_amount in range [0, 1]"
    # check articulated_objects.WoodenCabinet for the ranges
    # max open range seems to be -0.16, but fully_openn is -0.14 so there is some leeway (same with fully_closed=0)
    fully_open = max(self.object_properties["articulation"]["default_open_ranges"])
    fully_closed = min(self.object_properties["articulation"]["default_close_ranges"])
    threshold = open_amount * fully_open + (1-open_amount) * fully_closed
    return qpos < threshold

articulated_objects.WoodenCabinet.is_partial_open = wooden_cabinet_is_partial_open

def is_partial_open(self, open_amount):
    # Checks whether any joint is open by open_amounts
    for joint in self.env.object_sites_dict[self.object_name].joints:
        qpos_addr = self.env.sim.model.get_joint_qpos_addr(joint)
        qpos = self.env.sim.data.qpos[qpos_addr]
        if self.env.get_object(self.parent_name).is_partial_open(qpos, open_amount):
            return True
    return False

class PartialOpen(MultiarayAtomic):
    def __call__(self, *args):
        assert len(args) >= 2
        open_amount = float(args[1])
        return args[0].is_partial_open(open_amount)
    
VALIDATE_PREDICATE_FN_DICT["partialopen"] = PartialOpen()
BaseObjectState.is_partial_open = is_partial_open