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

	if (command == "calibrate")
	{
		std::string sessionPathStr;

        for (int i = 2; i < argc; ++i) 
		{
            std::string arg = argv[i];
            if ((arg == "-s" || arg == "--session") && i + 1 < argc) sessionPathStr = argv[++i];
        }

		if (sessionPathStr.empty())
		{
			Log::error("Error: Calibrate requires -s (session path).");
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
		}
		
		if (pathString.empty())
		{
			Log::error("Error: Path not specified.");
			logUsage(argv);
			return EXIT_FAILURE;
		}

		std::string sessionName = "session_" + getCurrentTimestamp();
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
	Log::error("Usage: ", cmd, " <command> [options]\n\n",
			   "Commands:\n",
			   "  record       Start recording\n",
			   "  calibrate    Start calibration\n\n",
			   "record Options:\n",
			   "  -p, --path <path>   (Required) base output path for sessions\n",
			   "  -v, --visualize     (Optional) enable preview\n\n",
			   "calibrate Options:\n",
			   "  -s, --session <path> (Required) path to session directory");
}
