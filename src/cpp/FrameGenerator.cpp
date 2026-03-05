#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <vector>

#include <dv-processing/core/core.hpp>
#include <dv-processing/io/stereo_camera_recording.hpp>

#include "FrameGenerator.h"
#include "Log.h"

namespace FrameGen
{
	static std::string shellQuote(const std::string &value)
	{
		std::string quoted = "'";
		for (char c : value)
		{
			if (c == '\'')
			{
				quoted += "'\\''";
			}
			else
			{
				quoted += c;
			}
		}
		quoted += "'";
		return quoted;
	}

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
			Log::error("Environment 'sert-python' missing.");
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


	int runE2VID(const std::filesystem::path& eventFile, const std::filesystem::path& outputDir, const std::string& datasetName, const RenderOptions& options)
	{
		std::filesystem::path e2vidPath = std::filesystem::path(PROJECT_ROOT_DIR) / "rpg_e2vid" / "run_reconstruction.py";
		std::filesystem::path modelPath = std::filesystem::path(PROJECT_ROOT_DIR) / "data" / "models" / "e2vid" / "E2VID_lightweight.pth.tar";
		
		std::vector<std::string> filteredArgs;
		for (size_t i = 0; i < options.extraArgs.size(); ++i)
		{
			if (options.extraArgs[i] == "--path_to_model" && i + 1 < options.extraArgs.size())
			{
				modelPath = options.extraArgs[i + 1];
				++i;
			}
			else
			{
				filteredArgs.push_back(options.extraArgs[i]);
			}
		}
		
		if (!std::filesystem::exists(e2vidPath))
		{
			Log::error("Could not find E2VID script at: ", e2vidPath.string());
			return EXIT_FAILURE;
		}

		if (!std::filesystem::exists(modelPath))
		{
			Log::error("Could not find E2VID model at: ", modelPath.string());
			Log::error("Run scripts/install_python_env.sh to download the model.");
			return EXIT_FAILURE;
		}

		if (environment_installed() != EXIT_SUCCESS)
		{
			Log::error("Conda environment could not be found! Aborting...");
			return EXIT_FAILURE;
		}

		std::string command = "conda run --no-capture-output -n sert-python python3 -u " + shellQuote(e2vidPath.string()) + " "
							+ "--path_to_model " + shellQuote(modelPath.string()) + " "
							+ "--input_file " + shellQuote(eventFile.string()) + " "
							+ "--output_folder " + shellQuote(outputDir.string()) + " "
							+ "--dataset_name " + shellQuote(datasetName) + " "
							+ "--fixed_duration "
							+ "--window_duration 33.33 "; // 33.33ms
							// + "--display ";

		for (const auto &arg : filteredArgs)
		{
			command += shellQuote(arg) + " ";
		}

		Log::info("Executing E2VID: ", command);

		int result = std::system(command.c_str());
		return (result == 0) ? EXIT_SUCCESS : EXIT_FAILURE;
	}

	int runECNN(const std::filesystem::path& txtFile, const std::filesystem::path& outputDir, const std::string& datasetName, const RenderOptions& options)
	{
		std::filesystem::path h5File = txtFile;
		h5File.replace_extension(".h5");

		std::filesystem::path txtToH5Path = std::filesystem::path(PROJECT_ROOT_DIR) / "src" / "python" / "txt_to_h5.py";
		std::filesystem::path inferencePath = std::filesystem::path(PROJECT_ROOT_DIR) / "event_cnn_minimal" / "inference.py";

		std::filesystem::path modelDir = std::filesystem::path(PROJECT_ROOT_DIR) / "data" / "models" / "event_cnn_minimal";
		std::filesystem::path modelPath;
		bool useUpdate = (options.model == "e2vidplusupdate");

		if (options.model == "e2vidplus")
		{
			modelPath = modelDir / "reconstruction" / "reconstruction_model.pth";
		}
		else if (options.model == "e2vidplusupdate")
		{
			modelPath = modelDir / "reconstruction" / "update_reconstruction_model.pth";
		}
		else if (options.model == "firenet")
		{
			modelPath = modelDir / "firenet" / "firenet_all_cts.pth";
		}

		std::vector<std::string> filteredArgs;
		for (size_t i = 0; i < options.extraArgs.size(); ++i)
		{
			if (options.extraArgs[i] == "--checkpoint_path" && i + 1 < options.extraArgs.size())
			{
				modelPath = options.extraArgs[i + 1];
				++i;
			}
			else if (options.extraArgs[i] == "--update")
			{
				useUpdate = true;
			}
			else
			{
				filteredArgs.push_back(options.extraArgs[i]);
			}
		}

		if (!std::filesystem::exists(modelPath))
		{
			Log::error("Could not find event_cnn_minimal model at: ", modelPath.string());
			Log::error("Run scripts/install_python_env.sh to download the models.");
			return EXIT_FAILURE;
		}

		if (environment_installed() != EXIT_SUCCESS)
		{
			Log::error("Conda environment could not be found! Aborting...");
			return EXIT_FAILURE;
		}

		if (!std::filesystem::exists(h5File))
		{
			std::string h5Cmd = "conda run --no-capture-output -n sert-python python3 -u "
								+ shellQuote(txtToH5Path.string()) + " "
								+ shellQuote(txtFile.string()) + " "
								+ shellQuote(h5File.string());
			Log::info("Converting txt to h5: ", h5Cmd);
			if (std::system(h5Cmd.c_str()) != 0)
			{
				return EXIT_FAILURE;
			}
		}

		std::string command = "conda run --no-capture-output -n sert-python python3 -u " + shellQuote(inferencePath.string()) + " "
							+ "--checkpoint_path " + shellQuote(modelPath.string()) + " "
							+ "--events_file_path " + shellQuote(h5File.string()) + " "
							+ "--output_folder " + shellQuote((outputDir / datasetName).string()) + " "
							+ "--voxel_method t_seconds "
							+ "--t 0.03333 "
							+ "--sliding_window_t 0 ";

		if (useUpdate)
		{
			command += "--update ";
		}

		if (options.device != "auto")
		{
			command += "--device " + options.device + " ";
		}

		for (const auto &arg : filteredArgs)
		{
			command += shellQuote(arg) + " ";
		}

		Log::info("Executing ECNN: ", command);

		int result = std::system(command.c_str());
		return (result == 0) ? EXIT_SUCCESS : EXIT_FAILURE;
	}
	
	int recordingToVideo(const std::filesystem::path &intermediateDir, const std::filesystem::path &reconstructionDir, const RenderOptions& options)
	{
		std::filesystem::path leftTxt = intermediateDir / "leftEvents.txt";	
		std::filesystem::path rightTxt = intermediateDir / "rightEvents.txt";	
		
		std::string backendStr = options.model == "e2vid" ? "rpg_e2vid" : "event_cnn_minimal";
		Log::info("Starting Reconstruction with backend: ", backendStr, " [Model: ", options.model, "]");

		if (options.model == "e2vid" && options.device != "auto")
		{
			Log::warn("Device override is not supported by rpg_e2vid backend yet. Using backend auto selection.");
		}

		auto runner = options.model == "e2vid" ? runE2VID : runECNN;

		if (runner(leftTxt, reconstructionDir, "left", options) != EXIT_SUCCESS)
		{
			Log::error(backendStr, " failed for left camera");
			return EXIT_FAILURE;
		}
		if (runner(rightTxt, reconstructionDir, "right", options) != EXIT_SUCCESS)
		{
			Log::error(backendStr, " failed for right camera");
			return EXIT_FAILURE;
		}

		Log::info("Reconstruction complete!");
		return EXIT_SUCCESS;
		
	}

}
