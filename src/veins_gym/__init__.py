#
# Copyright (C) 2020 Dominik S. Buse, <buse@ccs-labs.org>, Max Schettler <schettler@ccs-labs.org>
#
# Documentation for these modules is at http://veins.car2x.org/
#
# SPDX-License-Identifier: GPL-2.0-or-later
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
#

"""
Veins-Gym base structures to create gym environments from veins simulations.
"""

import atexit
import logging
import os
import signal
import subprocess
import sys
from typing import Any, Dict, NamedTuple

import gym
import numpy as np
import zmq
from gym import error, spaces, utils
from gym.utils import seeding

from . import veinsgym_pb2


class StepResult(NamedTuple):
    """Result record from one step in the invironment."""

    observation: Any
    reward: np.float32
    done: bool
    info: Dict


def ensure_valid_scenario_dir(scenario_dir):
    """
    Raise an exception if path is not a valid scenario directory.
    """
    if scenario_dir is None:
        raise ValueError("No scenario_dir given.")
    if not os.path.isdir(scenario_dir):
        raise ValueError("The scenario_dir does not point to a directory.")
    if not os.path.exists(os.path.join(scenario_dir, "omnetpp.ini")):
        raise FileNotFoundError(
            "The scenario_dir needs to contain an omnetpp.ini file."
        )
    return True


def launch_veins(
    scenario_dir,
    seed,
    port,
    print_stdout=False,
    extra_args=None,
    user_interface="Cmdenv",
    config="General",
):
    """
    Launch a veins experiment and return the process instance.

    All extra_args keys need to contain their own -- prefix.
    The respective values need to be correctly quouted.
    """
    command = [
        "./run",
        f"-u{user_interface}",
        f"-c{config}",
        f"--seed-set={seed}",
        f"--*.manager.seed={seed}",
        f"--*.gym_connection.port={port}",
    ]
    extra_args = dict() if extra_args is None else extra_args
    for key, value in extra_args.items():
        command.append(f"{key}={value}")
    logging.debug("Launching veins experiment using command `%s`", command)
    stdout = sys.stdout if print_stdout else subprocess.DEVNULL
    process = subprocess.Popen(command, stdout=stdout, cwd=scenario_dir)
    logging.debug("Veins process launched with pid %d", process.pid)
    return process


def shutdown_veins(process, gracetime_s=1.0):
    """
    Shut down veins if it still runs.
    """
    process.poll()
    if process.poll() is not None:
        logging.debug(
            "Veins process %d was shut down already with returncode %d.",
            process.pid,
            process.returncode,
        )
        return
    process.terminate()
    try:
        process.wait(gracetime_s)
    except subprocess.TimeoutExpired as _exc:
        logging.warning(
            "Veins process %d did not shut down gracefully, sennding kill.",
            process.pid,
        )
        process.kill()
    assert (
        process.poll() and process.returncode is not None
    ), "Veins could not be killed."


def serialize_action_discete(action):
    """Serialize a single discrete action into protobuf wire format."""
    reply = veinsgym_pb2.Reply()
    reply.action.discrete.value = action
    return reply.SerializeToString()


def parse_space(space):
    """Parse a Gym.spaces.Space from a protobuf request into python types."""
    if space.HasField("discrete"):
        return space.discrete.value
    if space.HasField("box"):
        return np.array(space.box.values, dtype=np.float32)
    if space.HasField("multi_discrete"):
        return np.array(space.multi_discrete.values, dtype=int)
    if space.HasField("multi_binary"):
        return np.array(space.multi_binary.values, dtype=bool)
    if space.HasField("tuple"):
        return tuple(parse_space(subspace) for subspace in space.tuple.values)
    if space.HasField("dict"):
        return {
            item.key: parse_space(item.space) for item in space.dict.values
        }
    raise RuntimeError("Unknown space type")


class VeinsEnv(gym.Env):
    metadata = {"render.modes": []}

    default_scenario_dir = None
    """
    Default scenario_dir argument for constructor.
    """

    def __init__(
        self,
        scenario_dir=None,
        run_veins=True,
        port=None,
        timeout=3.0,
        print_veins_stdout=False,
        action_serializer=serialize_action_discete,
        veins_kwargs=None,
        user_interface="Cmdenv",
        config="General",
    ):
        if scenario_dir is None:
            scenario_dir = self.default_scenario_dir
        assert ensure_valid_scenario_dir(scenario_dir)
        self.scenario_dir = scenario_dir
        self._action_serializer = action_serializer

        self.action_space = None
        self.observation_space = None

        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REP)
        self.port = port
        self.bound_port = None
        self._timeout = timeout
        self.print_veins_stdout = print_veins_stdout

        self.run_veins = run_veins
        self._passed_args = (
            veins_kwargs if veins_kwargs is not None else dict()
        )
        self._user_interface = user_interface
        self._config = config
        self._seed = 0
        self.veins = None
        self._veins_shutdown_handler = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.close()

    # Gym Env interface

    def step(self, action):
        """
        Run one timestep of the environment's dynamics.
        """
        self.socket.send(self._action_serializer(action))
        step_result = self._parse_request(self._recv_request())
        if step_result.done:
            self.socket.send(
                self._action_serializer(self.action_space.sample())
            )
            logging.debug("Episode ended, waiting for veins to finish")
            self.veins.wait()
        assert self.observation_space.contains(step_result.observation)
        return step_result

    def reset(self):
        """
        Start and connect to a new veins experiment, return first observation.

        Shut down exisiting veins experiment processes and connections.
        Waits until first request from veins experiment has been received.
        """
        self.close()
        self.socket = self.context.socket(zmq.REP)
        if self.port is None:
            self.bound_port = self.socket.bind_to_random_port(
                "tcp://127.0.0.1"
            )
            logging.debug("Listening on random port %d", self.bound_port)
        else:
            self.socket.bind(f"tcp://127.0.0.1:{self.port}")
            self.bound_port = self.port
            logging.debug("Listening on configured port %d", self.bound_port)

        if self.run_veins:
            self.veins = launch_veins(
                self.scenario_dir,
                self._seed,
                self.bound_port,
                self.print_veins_stdout,
                self._passed_args,
                self._user_interface,
                self._config,
            )
            logging.info("Launched veins experiment, waiting for request.")

            def veins_shutdown_handler(signum=None, stackframe=None):
                """
                Ensure that veins always gets shut down on python exit.

                This is implemented as a local function on purpose.
                There could be more than one VeinsEnv in one python process.
                So calling atexit.unregister(shutdown_veins) could cause leaks.
                """
                shutdown_veins(self.veins)
                if signum is not None:
                    sys.exit()

            atexit.register(veins_shutdown_handler)
            signal.signal(signal.SIGTERM, veins_shutdown_handler)
            self._veins_shutdown_handler = veins_shutdown_handler

        initial_request = self._parse_request(self._recv_request())[0]
        logging.info("Received first request from Veins, ready to run.")
        return initial_request

    def render(self, mode="human"):
        """
        Render current environment (not supported by VeinsEnv right now).
        """
        raise NotImplementedError(
            "Rendering is not implemented for this VeinsGym"
        )

    def close(self):
        """
        Close the episode and shut down veins scenario and connection.
        """
        logging.info("Closing VeinsEnv.")
        if self._veins_shutdown_handler is not None:
            atexit.unregister(self._veins_shutdown_handler)

        if self.veins:
            # TODO: send shutdown message (which needs to be implemted in veins code)
            shutdown_veins(self.veins)
            self.veins = None

        if self.bound_port:
            logging.debug("Closing VeinsEnv server socket.")
            self.socket.unbind(f"tcp://127.0.0.1:{self.bound_port}")
            self.socket.close()
            self.socket = None
            self.bound_port = None
            self.veins = None

    def seed(self, seed=None):
        """
        Set and return seed for the next episode.

        Will generate a random seed if None is passed.
        """
        if seed is not None:
            logging.debug("Setting given seed %d", seed)
            self._seed = seed
        else:
            random_seed = gym.utils.seeding.create_seed(max_bytes=4)
            logging.debug("Setting random seed %d", random_seed)
            self._seed = seed
        return [self._seed]

    # Internal helpers

    def _recv_request(self):
        rlist, _, _ = zmq.select([self.socket], [], [], timeout=self._timeout)
        if not rlist:
            logging.error(
                "Veins instance with PID %d timed out after %.2f seconds",
                self.veins.pid,
                self._timeout,
            )
            raise TimeoutError(
                f"Veins instance did not send a request within {self._timeout}"
                " seconds"
            )
        assert rlist == [self.socket]
        return self.socket.recv()

    def _parse_request(self, data):
        request = veinsgym_pb2.Request()
        request.ParseFromString(data)
        if request.HasField("shutdown"):
            return StepResult(self.observation_space.sample(), 0.0, True, {})
        if request.HasField("init"):
            # parse spaces
            self.action_space = eval(request.init.action_space_code)
            self.observation_space = eval(request.init.observation_space_code)
            # sent empty reply
            init_msg = veinsgym_pb2.Reply()
            self.socket.send(init_msg.SerializeToString())
            # request next request (actual request with content)
            real_data = self._recv_request()
            real_request = veinsgym_pb2.Request()
            real_request.ParseFromString(real_data)
            # continue processing the real request
            request = real_request
        observation = parse_space(request.step.observation)
        reward = parse_space(request.step.reward)
        assert len(reward) == 1
        return StepResult(observation, reward[0], False, {})
