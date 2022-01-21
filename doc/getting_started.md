Getting Started with Veins-Gym
==============================

This guide is intended to give you some hints on how to set up your own environments with Veins-Gym.
It's a rough outline for now and assumes you have at least some knowledge of Reinforcement Learning (RL) and V2X.
We will use the [serpentine-env](https://github.com/tkn-tub/serpentine-env) as an example and show how that was built.

In general, you will need the following components for your own Veins-Gym environment:

- a traffic scenario (in/via SUMO)
- a V2X simulation experiment (in Veins / OMNeT++)
- a data type description of actions, observations, and rewards (in Python / OpenAI gym shapes)
- an interface to your agent (in Veins / OMNeT++)

Let's go through them step by step


Traffic Scenario
----------------

To simulate vehicles and their mobility, Veins (and thus Veins-Gym) uses SUMO.
The definition of roads and traffic elements, such as cars, routes, and traffic lights, is done there.
At the very minimum, you need:

- a road network (`.net.xml` file)
- a set of vehicles with routes (typically a `.rou.xml` file)
- and a configuration file (`.sumo.cfg` file)

The [SUMO wiki](https://sumo.dlr.de/docs/) has excellent resources on how to build these scenarios, so head there to find out more.
Also note that there are many established scenarios for road traffic already.
Check out <https://sumo.dlr.de/docs/Data/Scenarios.html> or the [sss4s project](https://github.com/veins/sss4s).
You should always be able to test-drive your scenario by running it in `sumo-gui` and observe what is going on.

For the serpentine-env, we added these files as `scenario/serpentine.{net.xml,rou.xml,sumo.cfg}`.
This is primarily a single, very curvy road on which two vehicles will drive.
Both have the same route, maximum speed, and are spawned wit a little distance between them.
So the `leader` will drive ahead and the `follower` will stay somewhat close behind it.

There is also an alternative scenario (`scenario/lysevegen.{net.xml,rou.xml,sumo.cfg}`), but that is not important right now.
Just see that the same V2X simulation code can potentially run with different traffic scenarios.


V2X Simulation Experiment
-------------------------

Once you have vehicles driving around in SUMO, you can start simulating wireless communication among them using Veins.
With Veins, you can implement your own communication protocol and control which vehicles communicate.
An V2X simulation experiment is what we call a collection of C++ code files, `.ned` OMNeT++ configuration files, and an `omnetpp.ini` file that define a simulation.
It defines the communication behavior of the vehicles and everything they should do beyond driving around (the communication may even influence the driving behavior, e.g., in platooning).
Typically, this means implementing an application layer, e.g. by sub-classing `veins::BaseApplLayer`.
We assume you already have some experience with Veins and/or have an experiment at the ready.

We suggest you develop your V2X simulation experiment without any connection to an RL agent at first.
This way, you can run the simulation without the Gym-environment and an agent attached, which makes debugging much faster and easier.
While there probably will be decision the agent will have to make, you can typically simplify that in the beginning.
E.g., by using hard-coded or random decisions, or implementing a simple algorithm directly in Veins.

For the `serpentine-env`, the simulation experiment is switching between two communication technologies to efficiently exchange messages between the `leader` and `follower`.
We wrote `veins::serpentin::SerpentineApp` as a new application layer to implement simple periodic beaconing.
We used a different `Car` module definition than the normal one provided by Veins, as we wanted to incorporate multiple communication technologies:
Our `serpentine.Car` has a `Nic80211p` for DSRC communication and two `NicVlc`s for visible light communication, as well as a `ISplitter` module to multiplex between those.

The module implementing the `ISplitter` interface is the major point of interest in the `serpentine-env`.
We provided the `GymSplitter` to do this.
It does also implement the interaction with the agent (which is the topic of the following sections).
But it also contains the code to implement what the car should do with the decision which will be made by the agent.
In short, the `GymSplitter` module receives all messages coming down the stack from the application layer.
It then decides (through `GymSplitter::getAccessTechnology()`) which communication technology to use for transmission: DSRC or VLC.
Then, it passes the message to the MAC layer of the selected technology stack.
For development, the `GymSplitter::getAccessTechnology()` method could easily be implemented without an agent connection by only using a random communication technology.

All the code specific to the `serpentine-env` experiment went into the `src/serpentine` directory, e.g., the `.cc`, `.h`, and `.ned` files.
The `omnetpp.ini` file was placed next to the traffic scenario configuration in the `scenario` directory.
To keep all dependencies close at hand, we added Veins directly into the repository under `lib/veins`.
Note that to implement visible light communication, we also embedded `veins_vlc` under `lib/veins_vlc`.
Finally, we added workflow definitions in the `Snakefile` to facilitate building both the dependencies and the `serpentine-env` experiment.


Data Type Descriptions of the Interface to the Agent
----------------------------------------------------

Now that the V2X Simulation experiment is running on its own, it is time to prepare the connection to an RL agent.
For that, we need to formalize the inputs and outputs of the agent: observations, rewards, and actions.
The concept of [OpenAI gyms](http://gym.openai.com/) is agnostic to the specifics of how these inputs and outputs looks.
It simply provides [spaces](https://github.com/openai/gym/tree/master/gym/spaces) to allow the environment to specify the data types.

For Veins-Gym, the reward is currently always a single scalar `float`.
The action and observation space are fully defined by the environment, though.

Identify the observations and actions an agent in your environment should use.
Then specify a definition of `spaces` in which the observations and actions can be encoded.

If your agent produces non-trivial actions, it may be necessary to provide a serialization adapter.
Simple scalars like `int`s or `float`s can be converted by Veins-Gym itself.
But more complex types are not converted automatically at the moment.
Instead, write a function that receives the actions from the agent and returns a `Reply` object.
This function can then be passed to the Veins-Gym environment via `gym.register`:
For example:

```python
from veins_gym import veinsgym_pb2

def serialize_action(actions):
	"""Serialize a list of floats into an action."""
	reply = veinsgym_pb2.Reply()
	reply.action.box.values.extend(actions)
	return reply.SerializeToString()

gym.register(
	id="veins-v1",
	entry_point="veins_gym:VeinsEnv",
	"action_serializer": serialize_action,
	# ...
)
```


For the `serpentine-env`, the decision is to choose to send a message among any of the DSRC radio, the VLC headlight or the VLC taillight.
We encoded this into a simple 3 bit bitmap, stored as a discrete number with 8 choices: `gym.spaces.Discrete(8)`.
The observations are more complex:
The agent receives the vector pointing from the `follower` to the `leader` vehicle and the angle of impact of that vector on the back of the `leader`.
Both of these values are encoded as two-dimensional vectors `float`s.
The value of the distance vector is unbounded, while the angle (implemented as a heading vector) is normalized to -1 to 1.
So we encoded these observations into a `Box` (vector) of 4 floats with embedded limits: `gym.spaces.Box(low=np.array([-np.inf, -np.inf, -1, -1], dtype=np.float32), high=np.array([np.inf, np.inf, 1, 1], dtype=np.float32))`.


Experiment to Agent Interface
-----------------------------

With the specification done, the last step is to implement the code in Veins that will communicate with the agent in the OpenAI environment (the Python script that also controls the agent).
Whenever a decision from the agent is required in the simulation experiment, observations have to be gathered and sent to the OpenAI environment.
Alongside, the reward for the last action performed should be included for training.
The agent will decide on an action and send that back to the Veins simulation, which in turn needs to be unpacked and fed back into the simulation behavior.

A useful tool for this is the `GymConnection` module available in the `serpentine-env` release: <https://github.com/tkn-tub/serpentine-env/blob/master/src/serpentine/>.
It can take care of connecting to the environment via a ZeroMQ socket.
To the simulation, it provides the `GymConnection::communicate` method, that gets passed a `Request` and returns the `Reply` of the agent.
Simply add a `GymConnection` module to your OMNeT++ scenario `.ned` file or somewhere else in the simulation.
The data type definitions of the observations and actions are simply passed as configuration to the `GymConnection` in the `omnetpp.ini` ([example](https://github.com/tkn-tub/serpentine-env/blob/master/scenario/omnetpp.ini#L129)).
The `GymConnection` then takes care of transmitting this to the OpenAI environment via the first message upon connection.

Veins-Gym uses [Google Protocol Buffers](https://developers.google.com/protocol-buffers/) for data serialization.
The [source `veinsgym.proto` file](https://github.com/tkn-tub/veins-gym/blob/master/protobuf/veinsgym.proto) is shipped with `Veins-Gym` and can be compiled to C++ using `protoc`.
It implements the complete set of [OpenAI Gym spaces](https://github.com/openai/gym/tree/master/gym/spaces), so no manual serialization is needed.

To communicate with the agent from the simulation then, construct and fill a `veinsgym::proto::Request` object, pass it to `GymConnection::communicate`, and process the returned `veinsgym::proto::Reply`.
Filling `Request` objects can be done dynamically by setting its `step.observation` and `step.reward`.
Access typically takes place via the `mutable_<fieldname>()` accessors and `Add()` methods for adding array values.
Just make sure that the resulting structure matches the data type description specified in the previous section.

For the `serpentine-env`, the agent is asked for a decision every time the `follower` wants to send a message.
The observation contains the relative positions of the `leader` and the `follower` as described above.
And the reward is computed from the success of the last communication and some cost based on the technologies used.
To implement this, we first collect the reward and observation form the simulation in the `GymSplitter` module.
The `computeReward` and `computeObservation` methods encapsulate this and return easy to handle native C++ values.
Then, we construct a `Request` object via the `GymSplitter::serializeObservation` method:
On a new `Request` object, a `Box` is created for the observation, and the contents of the passed observation array are copied into its `mutable_values()`.
For the reward, we also simply create a `Box` and add one value, which we set to the scalar reward passed into the function.
The value (an `int`) of the received `Response` of the agent is then extracted, converted into the internal `enum` and used for the selection of the corresponding technology stack.


Conclusion
----------

With these parts in place, you should be able to set up your agent and start training.

If you want to share your own environment, please contact us so we can add a link to the Veins-Gym docs.
Veins, Veins-Gym and the example `serpentine-env` are released under the GNU General Public License 2.0, so they can be incorporated easily into your open-source projects.
