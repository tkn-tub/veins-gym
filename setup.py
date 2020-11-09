from setuptools import setup

setup(name='veins_gym',
      version='0.0.1',
      install_requires=['gym', 'zmq', 'protobuf'],
      packages=['veins_gym'],
      package_dir={'': 'src'},
      data_files=[('protobuf', ['protobuf/veinsgym.proto'])],
)
