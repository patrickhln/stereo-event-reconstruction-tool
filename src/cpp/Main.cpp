#include <atomic>
#include <csignal>
#include <cstdlib>
#include <string>

#include "Log.h"
#include "Recorder.h"
#include "FrameGenerator.h"

void logUsage(char* argv[]);

static std::atomic<bool> stopSignal(false);

static void signalHandler(int)
{
	stopSignal.store(true);
}

std::string getCurrentTimestamp()
{
	auto now = std::chrono::system_clock::now();
	auto in_time_t = std::chrono::system_clock::to_time_t(now);
	std::stringstream ss;
	ss << std::put_time(std::localtime(&in_time_t), "%Y-%m-%d_%H-%M-%S");
    return ss.str();
}

int main (int argc, char *argv[])
{
	if (argc < 2)
	{
		logUsage(argv);
		return EXIT_FAILURE;
	}
	const std::string command = argv[1];

	std::signal(SIGINT, signalHandler);
	std::signal(SIGTERM, signalHandler);

	if (command == "render")
	{
		std::string sessionPathStr;

        for (int i = 2; i < argc; ++i) 
		{
            std::string arg = argv[i];
            if ((arg == "-s" || arg == "--session") && i + 1 < argc) sessionPathStr = argv[++i];
        }

		if (sessionPathStr.empty())
		{
			Log::error("Error: render requires -s (session path).");
			logUsage(argv);
			return EXIT_FAILURE;
		}
		
		std::filesystem::path sessionDir(sessionPathStr);
		std::filesystem::path rawDir = sessionDir / "raw";
		std::filesystem::path intermediateDir = sessionDir / "intermediate";
		std::filesystem::path reconstructionDir = sessionDir / "reconstruction";

		if (!std::filesystem::exists(rawDir))
		{
			Log::error("Invalid session: 'raw' directory missing in ", sessionDir.string());
			return EXIT_FAILURE;
		}

		std::filesystem::create_directories(intermediateDir);
		std::filesystem::create_directories(reconstructionDir);

		FrameGen::CameraMetadata meta = FrameGen::readMetadata(rawDir);

		std::filesystem::path recordingFile = rawDir / "stereo_recording.aedat4";
		if (FrameGen::convertAedat4ToTxt(recordingFile, intermediateDir, meta.leftCamName, meta.rightCamName) != EXIT_SUCCESS)
		{
			Log::error("Could not convert .aedat4 to .txt for further E2VID reconstruction. Aborting...");	
			return EXIT_FAILURE;
		}
		if (FrameGen::recordingToVideo(intermediateDir, reconstructionDir) != EXIT_SUCCESS)
		{
			Log::error("E2VID reconstruction failed. Aborting...");
			return EXIT_FAILURE;
		}
	}
	else if (command == "record")
	{		
		std::string pathString;
		std::string sessionName = "session_" + getCurrentTimestamp();
		bool visualize = false;
		for (int i = 2; i < argc; ++i)
		{
			std::string arg = argv[i];

			if(arg == "-v" || arg == "--visualize") 
				visualize = true;

			else if (arg == "-p" || arg == "--path")
			{
            	if (i + 1 < argc) 
				{
					pathString = argv[++i]; 
				} else 
				{
					Log::error("Error: ", arg," flag requires a path argument.");
                    logUsage(argv);
                    return EXIT_FAILURE;		
				}
			}
			else if (arg == "-n" || arg == "--name")
			{
				if (i + 1 < argc)
				{
					sessionName = "session_" + std::string(argv[++i]);
				} else 
				{
					Log::error("Error: ", arg," flag requires a name argument.");
                    logUsage(argv);
                    return EXIT_FAILURE;		
				}
			}
		}
		
		if (pathString.empty())
		{
			Log::error("Error: Path not specified.");
			logUsage(argv);
			return EXIT_FAILURE;
		}

		std::filesystem::path sessionDir = std::filesystem::path(pathString) / sessionName;

		std::filesystem::path rawDir = sessionDir / "raw";
		std::filesystem::path intermediateDir = sessionDir / "intermediate";
		std::filesystem::path reconstructionDir = sessionDir / "reconstruction";

		try 
		{
			std::filesystem::create_directories(rawDir);
			std::filesystem::create_directories(intermediateDir);
			std::filesystem::create_directories(reconstructionDir);
			Log::info("Created session: ", sessionDir.string());
		}
		catch (const std::exception& e)
		{
			Log::error("Failed to create session directories: ", e.what());
			return EXIT_FAILURE;
		}
		
		if (visualize) 
			Log::info("Visualization enabled.");

		return StereoRecorder::record(rawDir, visualize, stopSignal);	
	}
	else if (command == "calibrate")
	{
		std::string sessionPathStr;

		// int targetCols = 0;
		// int targetRows = 0;
		// float rowSpacingMeters = 0.0f;	
		// float colSpacingMeters = 0.0f;
		bool configProvided = false;

        for (int i = 2; i < argc; ++i) 
		{
            std::string arg = argv[i];
            if ((arg == "-s" || arg == "--session") && i + 1 < argc) sessionPathStr = argv[++i];
            if ((arg == "-c" || arg == "--config") && i + 4 < argc)
			{
				try 
				{
					// targetCols = std::stoi(argv[++i]);    
					//                targetRows = std::stoi(argv[++i]);    
					//                rowSpacingMeters = std::stof(argv[++i]);    
					//                colSpacingMeters = std::stof(argv[++i]);
					// configProvided = true;
				} catch (const std::exception& e) 
				{
					Log::error("Invalid numeric value in config: ", e.what());
                    return EXIT_FAILURE;
				}
				
			}
        }

		if (sessionPathStr.empty())
		{
			Log::error("Error: Calibrate requires -s (session path).");
			logUsage(argv);
			return EXIT_FAILURE;
		}

		if (!configProvided)
		{
				Log::error("Error: calibration requires --config <targetCols> <targetRows> <rowSpacingMeters> <colSpacingMeters> (checkerboard)");
				Log::info("For more information, please refer to https://github.com/ethz-asl/kalibr/wiki/calibration-targets");
				logUsage(argv);
				return EXIT_FAILURE;		
		}
		
		std::filesystem::path sessionDir(sessionPathStr);
		std::filesystem::path rawDir = sessionDir / "raw";
		std::filesystem::path intermediateDir = sessionDir / "intermediate";
		std::filesystem::path reconstructionDir = sessionDir / "reconstruction";
		std::filesystem::path configDir = sessionDir / "config";
		std::filesystem::path calibrationDir = sessionDir / "calibration";

		if (!std::filesystem::exists(reconstructionDir))
		{
			Log::error("Invalid session: 'reconstruction' directory missing in ", sessionDir.string());
			return EXIT_FAILURE;
		}

		std::filesystem::create_directories(configDir);
		std::filesystem::create_directories(calibrationDir);

		Log::info("Initialized config/ and calibration/ directories for session: ", sessionPathStr);

	}
	else
	{
		logUsage(argv);
		return EXIT_FAILURE;
	}
	return EXIT_SUCCESS;
}
void logUsage(char* argv[])
{
    const std::string cmd = argv[0];
    Log::info(
        "Usage: ", cmd, " <command> [options]\n\n",

        "Commands:\n",
        "  record       Creates a timestamped session in <path> and saves raw .aedat4 data\n",
        "  render       Processes raw data into frames/bags within the session directory\n",
        "  calibrate    Computes intrinsics/extrinsics from frames and updates session config\n",
        "  esvo         Runs 3D reconstruction and saves results to the session's esvo/ folder\n\n",

        "record Options:\n",
        "  -p, --path <dir>      (Required) Parent directory where 'session_YYYY-MM-DD..' or 'session_<name>' (if -n is provided) is created\n",
		"  -n, --name			 (Optional) gives the session a name instead of the YYYY-MM-DD_H_M_S suffix\n",
        "  -v, --visualize       (Optional) Enable live preview window\n\n",

        "render Options:\n",
        "  -s, --session <dir>   (Required) Path to the specific session folder to process\n\n",

        "calibrate Options:\n",
        "  -s, --session <dir>   (Required) Path to the session folder (outputs to /calibration/ and /config/)\n\n",

        "esvo Options:\n",
        "  -s, --session <dir>   (Required) Path to the session folder (outputs to /esvo/)\n\n",

		"For more information about the session structure, take a look at https://github.com/patrickhln/event-stereo-reconstruction README.md\n"
    );
}
