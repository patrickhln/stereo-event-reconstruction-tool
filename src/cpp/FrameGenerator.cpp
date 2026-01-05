#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>

#include <dv-processing/core/core.hpp>
#include <dv-processing/io/stereo_camera_recording.hpp>

#include "FrameGenerator.h"
#include "Log.h"

namespace FrameGen
{
	CameraMetadata readMetadata(const std::filesystem::path &directory)
	{
		std::filesystem::path metaPath = directory / "camera_metadata.txt";
		std::ifstream file(metaPath);
		CameraMetadata meta;

		if (!file.is_open()) {
			Log::error("Could not find metadata at: ", metaPath.string());
			return meta;
		}

		std::string line;
		// Skip the first "Do not change" line
		std::getline(file, line); 
		
		if (std::getline(file, line)) meta.leftCamName = line;
		
		std::getline(file, line); 
		
		if (std::getline(file, line)) meta.rightCamName = line;

		return meta;	
	}
	
	int environment_installed()
	{
		// TODO: change the way the path is handled here (maybe using make install
		// later)
		int result = std::system(SCRIPTS_DIR "check_env.sh");	
		int exit_code = 0;
		if (WIFEXITED(result)) 
		{
			exit_code = WEXITSTATUS(result);
		}
		if (exit_code == 0) 
		{
			Log::info("Environment found.");
			return EXIT_SUCCESS;
		} else if (exit_code == 1) 
		{
			Log::error("Environment E2VID missing.");
			return EXIT_FAILURE;
		} else 
		{
			Log::error("Conda missing or Script not found (Exit code: ", exit_code, ")");
			return EXIT_FAILURE;
		}	
		
		return EXIT_FAILURE;
	}

	int convertAedat4ToTxt(const std::filesystem::path& inputAedat4, const std::filesystem::path& outputDir, const std::string& leftCamName, const std::string& rightCamName) 
	{
		
		dv::io::StereoCameraRecording recording = dv::io::StereoCameraRecording(inputAedat4, leftCamName, rightCamName);
		
		if (recording.getLeftReader().isEventStreamAvailable() && recording.getRightReader().isEventStreamAvailable())
		{
			size_t leftLineCount = 0;
			size_t rightLineCount = 0;

			std::filesystem::path leftOutPath = outputDir / "leftEvents.txt";
			if (!std::filesystem::exists(leftOutPath))
			{
				std::ofstream leftOutFile(leftOutPath);
				leftOutFile << 640 << " " << 480 << "\n";
				// TODO: which recording?!
				Log::info("Converting .aedat4 recording to .txt in preperation for E2VID:");
				Log::info("Processing left events...");
				while (true) {
					auto leftEvents = recording.getLeftReader().getNextEventBatch();
					// dv::EventStore sliced;
					// for (size_t i = 0; i < (leftEvents->size()-1); i++)
					// {
					// 	sliced = leftEvents->slice(i, i+1);
					// }
					if(!leftEvents.has_value())
						break;
					for (const dv::Event &ev : *leftEvents)
					{

						// E2VID expects timestamps in seconds (float), not microseconds
						leftOutFile << std::fixed << std::setprecision(6) << (ev.timestamp() / 1e6) << " " << ev.x() << " " << ev.y() << " " << ev.polarity() << "\n";		
						leftLineCount++;
					}
				}
				leftOutFile.close();
				Log::info("Finished processing!\n","Left file has ", leftLineCount, " lines");
			}
			std::filesystem::path rightOutPath = outputDir / "rightEvents.txt";
			if (!std::filesystem::exists(rightOutPath))
			{
				std::ofstream rightOutFile(rightOutPath);
				rightOutFile << 640 << " " << 480 << "\n";
				Log::info("Processing right events...");
				while (true) {
					auto rightEvents = recording.getRightReader().getNextEventBatch();
					if(!rightEvents.has_value())
						break;
					for (const dv::Event &ev : *rightEvents)
					{
						// rightOutFile<< ev.timestamp() << " " << ev.x() << " " << ev.y() << " " << ev.polarity() << "\n";		
						// E2VID expects timestamps in seconds (float), not microseconds
						rightOutFile << std::fixed << std::setprecision(6) << (ev.timestamp() / 1e6) << " " << ev.x() << " " << ev.y() << " " << ev.polarity() << "\n";		
						rightLineCount++;
					}
				}
				rightOutFile.close();
				Log::info("Finished processing!\n","Right file has ", rightLineCount, " lines");
				Log::warn("The files ", leftOutPath, ", and ", rightOutPath, " were created. However they are quiet large. Consider removing them when E2VID finished the frame generation");			
			}
		}

		return EXIT_SUCCESS;
	}


	int runE2VID(const std::filesystem::path& eventFile, const std::filesystem::path& outputDir, const std::string& datasetName)
	{
		std::filesystem::path e2vidPath = std::filesystem::path(PROJECT_ROOT_DIR) / "rpg_e2vid" / "run_reconstruction.py";
		std::filesystem::path modelPath = std::filesystem::path(PROJECT_ROOT_DIR) / "rpg_e2vid" / "pretrained" / "E2VID_lightweight.pth.tar";
		
		if (!std::filesystem::exists(e2vidPath))
		{
			Log::error("Could not find E2VID script at: ", e2vidPath.string());
			return EXIT_FAILURE;
		}

		if (!std::filesystem::exists(modelPath))
		{
			Log::error("Could not find E2VID model at: ", modelPath.string());
			Log::error("Run scripts/install_e2vid_env.sh to download the model.");
			return EXIT_FAILURE;
		}

		if (environment_installed() != EXIT_SUCCESS)
		{
			Log::error("Conda environment could not be found! Aborting...");
			return EXIT_FAILURE;
		}

		std::string command = "conda run -n E2VID python3 " + e2vidPath.string() + " "
							+ "--path_to_model " + modelPath.string() + " "
							+ "--input_file " + eventFile.string() + " "
							+ "--output_folder " + outputDir.string() + " "
							+ "--dataset_name " + datasetName + " "
							+ "--fixed_duration "
							+ "--window_duration 33 "; // 33ms
							// + "--no-normalize";
							// + "--display ";

		Log::info("Executing E2VID: ", command);

		int result = std::system(command.c_str());
		return (result == 0) ? EXIT_SUCCESS : EXIT_FAILURE;
	}
	
	int recordingToVideo(const std::filesystem::path &intermediateDir, const std::filesystem::path &reconstructionDir)
	{
		
		std::filesystem::path leftTxt = intermediateDir / "leftEvents.txt";	
		std::filesystem::path rightTxt = intermediateDir / "rightEvents.txt";	
		
		Log::info("Starting E2VID Reconstruction...");

		if (runE2VID(leftTxt, reconstructionDir, "left") != EXIT_SUCCESS)
		{
			Log::error("E2VID failed for left camera");
			return EXIT_FAILURE;
		}
		if (runE2VID(rightTxt, reconstructionDir, "right") != EXIT_SUCCESS)
		{
			Log::error("E2VID failed for right camera");
			return EXIT_FAILURE;
		}

		Log::info("Reconstruction complete!");
		return EXIT_SUCCESS;
		
	}

}
