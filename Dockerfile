FROM python:3.8-buster AS builder

ENV SUMO_VERSION 1_6_0
ENV SUMO_HOME /opt/sumo
ENV OMNET_VERSION 5.6.2
ENV OMNET_HOME /opt/omnet

# Install system dependencies.
RUN apt-get update && apt-get -qq install \
	wget \
	g++ \
	make \
	cmake \
	libxerces-c-dev \
	libfox-1.6-0 libfox-1.6-dev \
	libgdal-dev \
	libproj-dev \
	python2.7 \
	swig \
	bison \
	flex \
	libxml2-dev \
	zlib1g-dev \
	&& rm -rf /var/lib/apt/lists/*

# Build SUMO

# Download and extract source code
RUN cd /tmp &&\
	wget -q -O /tmp/sumo.tar.gz https://github.com/eclipse/sumo/archive/v$SUMO_VERSION.tar.gz &&\
	tar xzf sumo.tar.gz && \
	mv sumo-$SUMO_VERSION $SUMO_HOME && \
	rm sumo.tar.gz

# Configure and build from source.
RUN cd $SUMO_HOME &&\
	sed -i 's/endif (PROJ_FOUND)/\tadd_compile_definitions(ACCEPT_USE_OF_DEPRECATED_PROJ_API_H)\n\0/' CMakeLists.txt &&\
	mkdir build/cmake-build &&\
	cd build/cmake-build &&\
	cmake -DCMAKE_BUILD_TYPE:STRING=Release ../.. &&\
	make -j$(nproc)

# Build OMNeT++

# Download and extract source code
RUN wget https://github.com/omnetpp/omnetpp/releases/download/omnetpp-$OMNET_VERSION/omnetpp-$OMNET_VERSION-src-core.tgz \
	--referer=https://omnetpp.org/ \
	--progress=dot:giga \
	-O omnetpp-src-core.tgz \
	&& tar xf omnetpp-src-core.tgz \
	&& mv omnetpp-$OMNET_VERSION $OMNET_HOME \
	&& rm omnetpp-src-core.tgz

# Configure and build from source.
RUN export PATH=$OMNET_HOME/bin:$PATH \
	&& cd $OMNET_HOME \
	&& ./configure WITH_QTENV=no WITH_OSG=no WITH_OSGEARTH=no \
	&& make -j $(nproc) MODE=debug \
	&& make -j $(nproc) MODE=release \
	&& rm -r doc out test samples misc config.log config.status


# construct final container
FROM python:3.8-buster
MAINTAINER Dominik S. Buse (buse@ccs-labs.org)
LABEL Description="Dockerised Veins-Gym base container"

ENV SUMO_VERSION 1_6_0
ENV SUMO_HOME /opt/sumo
ENV OMNET_VERSION 5.6.2
ENV OMNET_HOME /opt/omnet
ENV VEINSGYM_VERSION 0.2.1

RUN apt-get update && apt-get -qq install \
	libgdal20 \
	libc6 \
	libfox-1.6-0 \
	libgcc1 \
	libgdal20 \
	libgl1 \
	libgl2ps1.4 \
	libglu1 \
	libproj13 \
	libstdc++6 \
	libxerces-c3.2 \
	libprotobuf-dev \
	libzmq3-dev \
	protobuf-compiler \
	&& rm -rf /var/lib/apt/lists/*

# copy over sumo
RUN mkdir -p $SUMO_HOME
COPY --from=builder $SUMO_HOME/data $SUMO_HOME/data
COPY --from=builder $SUMO_HOME/tools $SUMO_HOME/tools
COPY --from=builder $SUMO_HOME/bin $SUMO_HOME/bin
# copy in pre-compiled OMNeT++
COPY --from=builder /opt/omnet /opt/omnet

# update PATH
ENV PATH="$SUMO_HOME/bin:$OMNET_HOME/bin:${PATH}"

# install snakemake and veins_gym via pip
RUN python3 -m pip install snakemake veins_gym==$VEINSGYM_VERSION --no-cache
