from collections import deque

from stable_baselines3.common.callbacks import BaseCallback, EvalCallback
from stable_baselines3.common.base_class import BaseAlgorithm
from stable_baselines3.common.logger import Video
import numpy as np
import torch as th

class TensorboardCallback(BaseCallback):
    """
    Custom callback for plotting additional values in tensorboard.
    """

    def __init__(self, verbose=0):
        super(TensorboardCallback, self).__init__(verbose)

    def _on_step(self) -> bool:
        for index, custom_attributes in enumerate(self.training_env.get_attr('custom_attr')):
            self.logger.record(f'total reward for env {index}', custom_attributes.get('total_reward'))
            self.logger.record(f'reward for env {index}', custom_attributes.get('reward'))
        return True

class DebugCallback(BaseCallback):
    """
    A custom callback for logging debugging criteria
    """
    def __init__(self, verbose=0):
        super(DebugCallback, self).__init__(verbose)

    def _on_step(self) -> bool:
        pass
    

class VideoWriter(BaseCallback):
    """
    A custom callback for writing videos of the agent's performance.
    """
    def __init__(self, n_steps: int):
        super().__init__()
        self.n_steps = n_steps
        self.last_time_trigger = 0
        self.frame_buffer = deque(maxlen=250)

    def _on_step(self) -> bool:
        infos = self.locals["infos"][0]  # only log the first environment
        frame = infos["agentview_image"].transpose(2, 0, 1)[:, ::-1, ::-1]
        self.frame_buffer.append(frame)
        if (self.num_timesteps - self.last_time_trigger) >= self.n_steps:
            self.last_time_trigger = self.num_timesteps
            frames = th.tensor(np.stack(self.frame_buffer)).unsqueeze(0)

            logger = self.locals.get("self").logger
            logger.record("video/agent_view", Video(frames, fps=30), exclude="stdout")
        return True
    

class RLeXploreWithOnPolicyRL(BaseCallback):
    """
    A custom callback for combining RLeXplore and on-policy algorithms from SB3.
    """
    def __init__(self, irs, verbose=0):
        super(RLeXploreWithOnPolicyRL, self).__init__(verbose)
        self.irs = irs
        self.buffer = None

    def init_callback(self, model: BaseAlgorithm) -> None:
        super().init_callback(model)
        self.buffer = self.model.rollout_buffer
        self.loss_buffer = deque(maxlen=50)
        self.intrinsic_reward_buffer = deque(maxlen=50)

    def _on_step(self) -> bool:
        """
        This method will be called by the model after each call to `env.step()`.

        :return: (bool) If the callback returns False, training is aborted early.
        """
        observations = self.locals["obs_tensor"]
        device = observations.device
        actions = th.as_tensor(self.locals["actions"], device=device)
        rewards = th.as_tensor(self.locals["rewards"], device=device)
        dones = th.as_tensor(self.locals["dones"], device=device)
        next_observations = th.as_tensor(self.locals["new_obs"], device=device)

        # ===================== watch the interaction ===================== #
        self.irs.watch(observations, actions, rewards, dones, dones, next_observations)
        # ===================== watch the interaction ===================== #
        return True

    def _on_rollout_end(self) -> None:
        # ===================== compute the intrinsic rewards ===================== #
        # prepare the data samples
        obs = th.as_tensor(self.buffer.observations)
        # get the new observations
        new_obs = obs.clone()
        new_obs[:-1] = obs[1:]
        new_obs[-1] = th.as_tensor(self.locals["new_obs"])
        actions = th.as_tensor(self.buffer.actions)
        rewards = th.as_tensor(self.buffer.rewards)
        dones = th.as_tensor(self.buffer.episode_starts)
        print(obs.shape, actions.shape, rewards.shape, dones.shape, obs.shape)
        # compute the intrinsic rewards
        intrinsic_rewards = self.irs.compute(
            samples=dict(observations=obs, actions=actions, 
                         rewards=rewards, terminateds=dones, 
                         truncateds=dones, next_observations=new_obs),
            sync=True)
        
        # update the intrinsic reward module
        self.irs.update(samples=dict(observations=obs, actions=actions,
                                    rewards=rewards, terminateds=dones,
                                    truncateds=dones, next_observations=new_obs))
        self.loss_buffer.append(self.irs.metrics["loss"][-1])
        self.intrinsic_reward_buffer.append(np.mean(intrinsic_rewards.cpu().numpy()))

        # add the intrinsic rewards to the buffer
        self.buffer.rewards += intrinsic_rewards.cpu().numpy()
        # compute the advantages again
        values = self.locals["values"]
        dones = self.locals["dones"]
        self.buffer.compute_returns_and_advantage(last_values=values, dones=dones)

        self.locals["self"].logger.record("intrinsic_reward/loss", np.mean(self.loss_buffer))
        self.locals["self"].logger.record("intrinsic_reward/reward", np.mean(self.intrinsic_reward_buffer))
        
        # ===================== compute the intrinsic rewards ===================== #

class RLeXploreWithOffPolicyRL(BaseCallback):
    """
    A custom callback for combining RLeXplore and off-policy algorithms from SB3. 
    """
    def __init__(self, irs, verbose=0):
        super(RLeXploreWithOffPolicyRL, self).__init__(verbose)
        self.irs = irs
        self.buffer = None

    def init_callback(self, model: BaseAlgorithm) -> None:
        super().init_callback(model)
        self.buffer = self.model.replay_buffer
        

    def _on_step(self) -> bool:
        """
        This method will be called by the model after each call to `env.step()`.

        :return: (bool) If the callback returns False, training is aborted early.
        """
        device = self.irs.device
        obs = th.as_tensor(self.locals['self']._last_obs, device=device)
        actions = th.as_tensor(self.locals["actions"], device=device)
        rewards = th.as_tensor(self.locals["rewards"], device=device)
        dones = th.as_tensor(self.locals["dones"], device=device)
        next_obs = th.as_tensor(self.locals["new_obs"], device=device)
        # ===================== watch the interaction ===================== #
        self.irs.watch(obs, actions, rewards, dones, dones, next_obs)
        # ===================== watch the interaction ===================== #
        # ===================== compute the intrinsic rewards ===================== #
        intrinsic_rewards = self.irs.compute(samples={'observations':obs.unsqueeze(0).float(), 
                                            'actions':actions.unsqueeze(0), 
                                            'rewards':rewards.unsqueeze(0),
                                            'terminateds':dones.unsqueeze(0),
                                            'truncateds':dones.unsqueeze(0),
                                            'next_observations':next_obs.unsqueeze(0).float()}, 
                                            sync=False)
        # ===================== compute the intrinsic rewards ===================== #
        # add the intrinsic rewards to the original rewards
        self.locals['rewards'] += intrinsic_rewards.cpu().numpy().squeeze()
        # Zifan: check if this value is indeed added back to the reward in storage

        try:
            # update the intrinsic reward module
            replay_data = self.buffer.sample(batch_size=self.irs.batch_size)
            self.irs.update(samples={'observations': th.as_tensor(replay_data.observations).unsqueeze(1).to(device), # (n_steps, n_envs, *obs_shape)
                                     'actions': th.as_tensor(replay_data.actions).unsqueeze(1).to(device),
                                     'rewards': th.as_tensor(replay_data.rewards).to(device),
                                     'terminateds': th.as_tensor(replay_data.dones).to(device),
                                     'truncateds': th.as_tensor(replay_data.dones).to(device),
                                     'next_observations': th.as_tensor(replay_data.next_observations).unsqueeze(1).to(device)
                                     })
        except:
            pass

        return True

    def _on_rollout_end(self) -> None:
        pass


class StopTrainingOnSuccessRateThreshold(BaseCallback):
    """
    Stop the training once a threshold in success rate has been reached

    It must be used with the ``EvalCallback``.

    :param threshold:  Minimum expected success rate to stop training.
    :param n_times:  The threshold must be met this number of consecutive times to stop training
    :param verbose: Verbosity level: 0 for no output, 1 for indicating when training ended because episodic reward
        threshold reached
    """

    parent: EvalCallback

    def __init__(self, threshold: float, n_times: int = 1, verbose: int = 0):
        super().__init__(verbose=verbose)
        self.threshold = threshold
        self.n_times = n_times
        self.met_threshold_count = 0

    def _on_step(self) -> bool:
        assert self.parent is not None, "``StopTrainingOnSuccessRateThreshold`` callback must be used with an ``EvalCallback``"
        success_rate = np.mean(self.parent._is_success_buffer)
        met_threshold = bool(success_rate > self.threshold)
        if met_threshold:
            self.met_threshold_count += 1
            print(f"Success rate {success_rate} is above threshold {self.threshold}. Count is now {self.met_threshold_count}")
        else:
            self.met_threshold_count = 0
        continue_training = self.met_threshold_count < self.n_times
        if self.verbose >= 1 and not continue_training:
            print(f"Stopping training because the success rate was above the threshold {self.threshold} for {self.n_times} times")
        return continue_training
    