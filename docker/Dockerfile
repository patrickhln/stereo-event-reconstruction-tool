# ROS Noetic (Ubuntu 20.04)
FROM ros:noetic-ros-base

# prevent interactive promts like timezone selection
ENV DEBIAN_FRONTEND=noninteractive

SHELL ["/bin/bash", "-c"]

# dependencies
RUN apt-get update && apt-get install -y \
    software-properties-common \
    git wget vim nano curl build-essential \
    python3-pip python3-catkin-tools python3-osrf-pycommon python3-vcstool \
    # add ubuntu-science repo for libcaer-dev
    && add-apt-repository ppa:ubuntu-toolchain-r/test \
    && add-apt-repository ppa:inivation-ppa/inivation \
    && apt-get update \
    # math libraries
    && apt-get install -y \
    libeigen3-dev libboost-all-dev libsuitesparse-dev \
    libblas-dev liblapack-dev \
    # opencv, tbb (parallel processing)
    libopencv-dev libpoco-dev libtbb-dev \
	libyaml-cpp-dev \
    # kalibr specifics
    python3-scipy python3-matplotlib python3-wxgtk4.0 \
    python3-igraph python3-pyx autoconf automake \
    libv4l-dev libcaer-dev \
    # ROS packages (images and coordinate transforms)
    ros-noetic-cv-bridge \
    ros-noetic-image-transport \
    ros-noetic-tf \
    ros-noetic-camera-info-manager \
    ros-noetic-image-view \
    ros-noetic-resource-retriever \
	ros-noetic-eigen-conversions \
	ros-noetic-tf-conversions \
	ros-noetic-image-geometry \
	ros-noetic-pcl-ros \
    ros-noetic-pcl-conversions \
    # cleanup
    && rm -rf /var/lib/apt/lists/*

# standard ROS directory structure
WORKDIR /catkin_ws/src

# Install Kalibr
RUN git clone --depth 1 https://github.com/ethz-asl/kalibr.git

# Install ESVO & dependencies 
RUN git clone --depth 1 https://github.com/HKUST-Aerial-Robotics/ESVO.git

# patch that fixes eigen 3.4 problem
# (https://github.com/Jas0nG/ESVO/tree/fix/eigen_3_4_0)
COPY ./esvo_eigen_fix.patch /catkin_ws/src/ESVO/esvo_eigen_fix.patch
# patch that applies changes to CmakeLists.txt for linker to work correctly
COPY ./esvo_linker_fix.patch /catkin_ws/src/ESVO/esvo_linker_fix.patch

RUN cd /catkin_ws/src/ESVO && \
    patch -p1 < esvo_eigen_fix.patch && \
    patch -p1 < esvo_linker_fix.patch

# dependencies.yaml contains a list to other git repos ESVO needs, vcs-import
# reads and clones automatically
RUN vcs-import < ESVO/dependencies.yaml

# minkindr_python requires catkin_boost_python_toolkit
RUN git clone --depth 1 https://github.com/ethz-asl/catkin_boost_python_buildtool.git

# build everything
WORKDIR /catkin_ws

# remove duplicate catkin_simple package inside kalibr 
# to avoid naming collisions with the standalone catkin_simple
RUN rm -rf src/kalibr/catkin_simple

RUN rosdep update || echo "rosdep already updated"

# installs everything missing
# --from-paths src: look at all package.xml files in src/
# --ignore-src: don't try to install things that are already in src/ (like catkin_simple)
# -r: continue despite errors (useful if some keys are missing)
# -y: yes to all prompts
RUN apt-get update && rosdep install --from-paths src --ignore-src -r -y


# use -j2 to prevent crashing on low-ram systems (kalibr is heavy)
RUN /bin/bash -c "source /opt/ros/noetic/setup.bash && \
	catkin init && \
	catkin config --extend /opt/ros/noetic && \
	catkin config --cmake-args -DCMAKE_BUILD_TYPE=Release && \
	catkin build -j2"

# setup entrypoint
COPY ./entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
CMD ["bash"]
