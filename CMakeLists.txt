cmake_minimum_required(VERSION 3.10)

project(sert)

set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/$<CONFIGURATION>")
# put .so objects next to binary
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/$<CONFIGURATION>")

set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

set(SOURCE_FILES
	src/cpp/Main.cpp
	src/cpp/Recorder.cpp
	src/cpp/FrameGenerator.cpp
	src/cpp/Calibrator.cpp
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
include_directories( ${OpenCV_INCLUDE_DIRS} )
target_link_libraries(${PROJECT_NAME}
	${OpenCV_LIBS}
	dv::processing
)
target_compile_features(${PROJECT_NAME} PRIVATE cxx_std_17)
target_compile_options(${PROJECT_NAME} PRIVATE -Wall -Wextra -Werror)



