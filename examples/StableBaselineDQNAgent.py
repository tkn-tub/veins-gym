##!/usr/bin/env python3
# !/home/parallels/tools_thesis/omnetpp-5.6.2/samples/lowerlossRL1/venv/bin/python3

# you will like to change the shebang above so it will use your paths instead

"""
DQN Agent from StableBaselines3 example.
"""
import time
import logging
import os
import random
import sys
import gym
import veins_gym
from veins_gym import veinsgym_pb2

from stable_baselines3 import DQN
from stable_baselines3.common.env_checker import check_env

"""
	This function needs to be adapted for your necessities
"""
def serialize_action(actions):
    """Searialize a list of floats into an action."""
    reply = veinsgym_pb2.Reply()
    if not hasattr(actions, '__iter__'):
        # make sure to have a vector of actions if you don't want to change veinsgym Env itself 
        # and you are usinf Discrete for actions
        actions = [actions]
    reply.action.box.values.extend(actions)

    return reply.SerializeToString()


gym.register(
    id="veins-v1",
    entry_point="veins_gym:VeinsEnv",
    kwargs={
        "scenario_dir": os.path.relpath(
            os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "..", "the_name_of_your_compiled_simulation_from_omnetpp"
            )
        ),
        # make sure you have an expressive timeout if your simulation is complex and loads lots of modules.
        "timeout": 50.0,
        "print_veins_stdout": True,
        "action_serializer": serialize_action,
        "run_veins": True,  # start veins through Veins-Gym
        "port": 5555,  # pick a port to use
        # to run in a GUI, use:
        "user_interface": "Cmdenv",
        
    },
)


def main():
    """
    Run the DQN agent.
    """
    logging.basicConfig(level=logging.DEBUG)

    env = gym.make("veins-v1")
    observation = env.reset()
    
    print("Observation space:", env.observation_space)
    print("Shape:", env.observation_space.shape)
    print("Action space:", env.action_space)

    # this check tool helps you to debug some common error you may have regarding the shape of your observations 
    # and actions and many others
    check_env(env)
    
    logging.info("Env created")

    model = DQN('MlpPolicy', env, verbose=1)
    
    #configurable time steps
    timesteps = 1800
    
    model.learn(total_timesteps=timesteps)
    
    episodes = 2
    rewards = []
    
    # If you use learn() as above, you don't exactly need episodes here. You can simply have while not done instead.
    for episode in range(0, episodes):
        observation = env.reset()
        logging.info("Env reset for episode %s", episode)

        action, _state = model.predict(observation,deterministic=True)
        
        observation, reward, done, info = env.step(action)

        while not done:
        
            action, _state = model.predict(observation,deterministic=True)
            
            observation, reward, done, info = env.step(action)
            #env.render()
            
            rewards.append(reward)
            # the last action sent by omnetpp to veinsgym will be a shutdown
            # and that will make the done be set to true. In the veinsgym code that this happens, it will
            # also generate a final random of the observation (in _parse request function)
            # that will be sent in step function
            # and must then be discarded (as it is an undesired step + 1 anyway)
            if not done:
                logging.debug(
                    "Last action: %s, Reward: %.3f, Observation: %s",
                    action,
                    reward,
                    observation,
                )
        print("Number of steps taken:", len(rewards))
        print("Mean reward:", sum(rewards) / len(rewards))
        print()
        rewards = []
        
        # You may see your ZMQ saying the socket is being used and crashing the python process. The sleep below can help with the issue.
        time.sleep(0.059)


if __name__ == "__main__":
    main()

