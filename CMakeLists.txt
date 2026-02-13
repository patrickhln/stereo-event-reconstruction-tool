cmake_minimum_required(VERSION 3.14)

# yaml-cpp 0.8.0 requires older CMake policy
set(CMAKE_POLICY_VERSION_MINIMUM 3.5)

project(sert)

set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/$<CONFIGURATION>")
# put .so objects next to binary
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/$<CONFIGURATION>")

set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

set(SOURCE_FILES
	src/cpp/Main.cpp
	src/cpp/Recorder.cpp
	src/cpp/FrameGenerator.cpp
	src/cpp/Aedat4Filter.cpp
	src/cpp/HotPixelFilter.cpp
	src/cpp/Calibrator.cpp
	src/cpp/Session.cpp
)

add_executable(${PROJECT_NAME} ${SOURCE_FILES})

target_compile_definitions(${PROJECT_NAME} PRIVATE
SCRIPTS_DIR="${CMAKE_SOURCE_DIR}/scripts/"
PROJECT_ROOT_DIR="${CMAKE_SOURCE_DIR}"
)

# Third Party Libraries
find_package(OpenCV REQUIRED)
# Suppress warning about FindBoost removal in dependencies
if(POLICY CMP0167)
  cmake_policy(SET CMP0167 OLD)
endif()
find_package(dv-processing REQUIRED)

# yaml-cpp for session configuration
include(FetchContent)
FetchContent_Declare(
	yaml-cpp
	GIT_REPOSITORY https://github.com/jbeder/yaml-cpp.git
	GIT_TAG 0.8.0
)
FetchContent_MakeAvailable(yaml-cpp)

include_directories( ${OpenCV_INCLUDE_DIRS} )
target_link_libraries(${PROJECT_NAME}
	${OpenCV_LIBS}
	dv::processing
	yaml-cpp::yaml-cpp
)
target_compile_features(${PROJECT_NAME} PRIVATE cxx_std_17)
target_compile_options(${PROJECT_NAME} PRIVATE -Wall -Wextra -Werror)



