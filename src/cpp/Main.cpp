#include <atomic>
#include <csignal>
#include <cstdlib>
#include <string>
#include <fstream>

#include "Log.h"
#include "Session.h"
#include "Recorder.h"
#include "FrameGenerator.h"
#include "Calibrator.h"

void logUsage(char* argv[]);

static std::atomic<bool> stopSignal(false);

static void signalHandler(int)
{
	stopSignal.store(true);
}

static std::filesystem::path normalizeSessionArg(const std::string& sessionPathStr)
{
	std::filesystem::path sessionPath = std::filesystem::path(sessionPathStr).lexically_normal();
	if (sessionPath.filename().empty())
	{
		sessionPath = sessionPath.parent_path();
	}
	return sessionPath;
}

static Session loadSessionFromPath(const std::string& sessionPathStr)
{
	std::filesystem::path sessionPath = normalizeSessionArg(sessionPathStr);
	if (!Session::isValidSession(sessionPath))
	{
		throw std::runtime_error("Invalid session path: " + sessionPath.string());
	}
	return Session::load(sessionPath);
}

static Session loadOrCreateSessionInParent(const std::string& parentPathStr, const std::string& sessionName)
{
	std::filesystem::path parentPath = normalizeSessionArg(parentPathStr);
	if (parentPath.empty())
	{
		parentPath = ".";
	}
	if (Session::isValidSession(parentPath))
	{
		throw std::runtime_error("Parent path is already a session: " + parentPath.string());
	}
	if (std::filesystem::exists(parentPath) && !std::filesystem::is_directory(parentPath))
	{
		throw std::runtime_error("Parent path is not a directory: " + parentPath.string());
	}
	if (!std::filesystem::exists(parentPath))
	{
		std::filesystem::create_directories(parentPath);
	}
	std::string normalizedName;
	if (!sessionName.empty())
	{
		normalizedName = "session_" + sessionName;
		std::filesystem::path sessionPath = parentPath / normalizedName;
		if (Session::isValidSession(sessionPath))
		{
			return Session::load(sessionPath);
		}
		if (std::filesystem::exists(sessionPath))
		{
			throw std::runtime_error("Session path exists but has no session.yaml: " + sessionPath.string());
		}
		return Session::create(parentPath, sessionName);
	}
	return Session::create(parentPath, "");
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
		std::string captureName;

		for (int i = 2; i < argc; ++i) 
		{
			std::string arg = argv[i];
			if ((arg == "-s" || arg == "--session") && i + 1 < argc) sessionPathStr = argv[++i];
			if ((arg == "-c" || arg == "--capture") && i + 1 < argc) captureName = argv[++i];
		}

		if (sessionPathStr.empty())
		{
			Log::error("Error: render requires -s (session path).");
			logUsage(argv);
			return EXIT_FAILURE;
		}

		if (captureName.empty())
		{
			Log::error("Error: render requires -c (capture name).");
			logUsage(argv);
			return EXIT_FAILURE;
		}

		try
		{
			Session session = loadSessionFromPath(sessionPathStr);
			std::filesystem::path captureDir = session.getCaptureDir(captureName);
			
			std::filesystem::path rawDir = Session::getRawDir(captureDir);
			std::filesystem::path intermediateDir = Session::getIntermediateDir(captureDir);
			std::filesystem::path framesDir = Session::getFramesDir(captureDir);

			if (!std::filesystem::exists(rawDir))
			{
				Log::error("Invalid capture: 'raw' directory missing in ", captureDir.string());
				return EXIT_FAILURE;
			}

			std::filesystem::create_directories(intermediateDir);
			std::filesystem::create_directories(framesDir);

			FrameGen::CameraMetadata meta = FrameGen::readMetadata(rawDir);

			std::filesystem::path recordingFile = rawDir / "stereo_recording.aedat4";
			if (FrameGen::convertAedat4ToTxt(recordingFile, intermediateDir, meta.leftCamName, meta.rightCamName) != EXIT_SUCCESS)
			{
				Log::error("Could not convert .aedat4 to .txt for further E2VID reconstruction. Aborting...");	
				return EXIT_FAILURE;
			}
			if (FrameGen::recordingToVideo(intermediateDir, framesDir) != EXIT_SUCCESS)
			{
				Log::error("E2VID reconstruction failed. Aborting...");
				return EXIT_FAILURE;
			}
		}
		catch (const std::exception& e)
		{
			Log::error("Error: ", e.what());
			return EXIT_FAILURE;
		}
	}
	else if (command == "record")
	{		
		std::string parentPathStr;
		std::string captureName;
		std::string captureType;
		std::string sessionName;
		bool visualize = false;

		for (int i = 2; i < argc; ++i)
		{
			std::string arg = argv[i];

			if(arg == "-v" || arg == "--visualize") 
				visualize = true;

			else if ((arg == "-p" || arg == "--parent") && i + 1 < argc)
				parentPathStr = argv[++i];

			else if ((arg == "-s" || arg == "--session") && i + 1 < argc)
				sessionName = argv[++i];

			else if ((arg == "-n" || arg == "--name") && i + 1 < argc)
				captureName = argv[++i];

			else if ((arg == "-t" || arg == "--type") && i + 1 < argc)
				captureType = argv[++i];
		}
		
		if (parentPathStr.empty())
		{
			Log::error("Error: Parent path not specified (-p).");
			logUsage(argv);
			return EXIT_FAILURE;
		}

		if (captureType.empty())
		{
			Log::error("Error: Capture type not specified (--type calib or --type scene).");
			logUsage(argv);
			return EXIT_FAILURE;
		}

		if (captureType != "calib" && captureType != "scene")
		{
			Log::error("Error: Invalid capture type '", captureType, "'. Must be 'calib' or 'scene'.");
			logUsage(argv);
			return EXIT_FAILURE;
		}

		try
		{
			Session session = loadOrCreateSessionInParent(parentPathStr, sessionName);

			CaptureType type = (captureType == "calib") ? CaptureType::CALIBRATION : CaptureType::SCENE;
			std::filesystem::path captureDir = session.createCapture(type, captureName);
			std::filesystem::path rawDir = Session::getRawDir(captureDir);

			if (visualize) 
				Log::info("Visualization enabled.");

			return StereoRecorder::record(rawDir, visualize, stopSignal);
		}
		catch (const std::exception& e)
		{
			Log::error("Error: ", e.what());
			return EXIT_FAILURE;
		}
	}
	else if (command == "calibrate")
	{
		std::string sessionPathStr;
		std::string captureName;
		std::string targetType;

		int cols = 0, rows = 0;
		float param3 = 0.0f; // tagSize, rowSpacing or spacing
		float param4 = 0.0f; // tagSpacing, colSpacing or asymmetric flag

		bool configProvided = false;

		for (int i = 2; i < argc; ++i) 
		{
			std::string arg = argv[i];
			if ((arg == "-s" || arg == "--session") && i + 1 < argc) sessionPathStr = argv[++i];
			if ((arg == "-c" || arg == "--capture") && i + 1 < argc) captureName = argv[++i];
			if ((arg == "-t" || arg == "--target") && i + 1 < argc) targetType = argv[++i];
			if ((arg == "--config") && i + 4 < argc)
			{
				try 
				{
					cols = std::stoi(argv[++i]);    
					rows = std::stoi(argv[++i]);    
					param3 = std::stof(argv[++i]);    
					param4 = std::stof(argv[++i]);
					configProvided = true;
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

		if (captureName.empty())
		{
			Log::error("Error: Calibrate requires -c (capture name).");
			logUsage(argv);
			return EXIT_FAILURE;
		}

		try
		{
			Session session = loadSessionFromPath(sessionPathStr);
			std::filesystem::path captureDir = session.getCaptureDir(captureName);
			
			std::filesystem::path rawDir = Session::getRawDir(captureDir);
			std::filesystem::path intermediateDir = Session::getIntermediateDir(captureDir);
			std::filesystem::path framesDir = Session::getFramesDir(captureDir);
			std::filesystem::path configDir = session.getTargetsDir();

			if (!std::filesystem::exists(framesDir))
			{
				Log::error("Invalid capture: 'frames' directory missing in ", captureDir.string());
				Log::error("Run 'sert render' first to generate frames.");
				return EXIT_FAILURE;
			}

			// check for existing target config in session config/targets/
			bool configExists = false;
			std::filesystem::path existingTargetPath;
			if (std::filesystem::exists(configDir))
			{
				for (const auto& entry : std::filesystem::directory_iterator(configDir))
				{
					std::string filename = entry.path().filename().string();
					if (filename == "aprilgrid.yaml" || filename == "checkerboard.yaml" || filename == "circlegrid.yaml")
					{
						configExists = true;
						existingTargetPath = entry.path();
						Log::info("Found existing calibration target config: ", entry.path().string());
						break;
					}
				}
			}

			if (!configExists && (targetType.empty() || !configProvided))
			{
				Log::error("Error: No existing calibration config found. Please provide -t and --config options.");
				logUsage(argv);
				return EXIT_FAILURE;
			}

			std::filesystem::create_directories(configDir);

			Log::info("Initialized calibration for capture: ", captureName);

			// write target config if provided
			if (!targetType.empty() && configProvided)
			{
				if (targetType == "aprilgrid")
				{
					std::ofstream calibrationConfig(configDir / "aprilgrid.yaml");
					calibrationConfig << "target_type: 'aprilgrid'" << "\n";
					calibrationConfig << "tagCols: " << cols << "\n";
					calibrationConfig << "tagRows: " << rows << "\n";
					calibrationConfig << "tagSize: " << param3 << "\n";
					calibrationConfig << "tagSpacing: " << param4 << "\n";
					calibrationConfig.close();
				}
				else if (targetType == "checkerboard") 
				{
					std::ofstream calibrationConfig(configDir / "checkerboard.yaml");
					calibrationConfig << "target_type: 'checkerboard'" << "\n";
					calibrationConfig << "targetCols: " << cols << "\n";
					calibrationConfig << "targetRows: " << rows << "\n";
					calibrationConfig << "rowSpacingMeters: " << param3 << "\n";
					calibrationConfig << "colSpacingMeters: " << param4 << "\n";
					calibrationConfig.close();
				}
				else if (targetType == "circlegrid") 
				{
					std::ofstream calibrationConfig(configDir / "circlegrid.yaml");
					calibrationConfig << "target_type: 'circlegrid'" << "\n";
					calibrationConfig << "targetCols: " << cols << "\n";
					calibrationConfig << "targetRows: " << rows << "\n";
					calibrationConfig << "spacingMeters: " << param3 << "\n";
					bool asymmetricGrid = static_cast<bool>(param4);
					asymmetricGrid == 0 ? calibrationConfig << "asymmetricGrid: False" << "\n" : calibrationConfig << "asymmetricGrid: True" << "\n"; 
					calibrationConfig.close();
				}
				else 
				{
					Log::error("Target type for calibration has to be one of 3: aprilgrid, checkerboard, circlegrid");
					logUsage(argv);
					return EXIT_FAILURE;
				}
			}

			// run calibration
			if (Calib::createRosBag(captureDir) != EXIT_SUCCESS)
			{
				Log::error("Failed to create ROS bag for calibration.");
				return EXIT_FAILURE;
			}

			if (Calib::run(session, captureDir) != EXIT_SUCCESS)
			{
				Log::error("Calibration failed.");
				return EXIT_FAILURE;
			}

			// auto-activate calibration on success
			try
			{
				session.setActiveCalibration(captureName);
				Log::info("Calibration successful! Set '", captureName, "' as active calibration.");
			}
			catch (const std::exception& e)
			{
				Log::warn("Calibration completed but could not auto-activate: ", e.what());
			}
		}
		catch (const std::exception& e)
		{
			Log::error("Error: ", e.what());
			return EXIT_FAILURE;
		}
	}
	else if (command == "set-calibration")
	{
		std::string sessionPathStr;
		std::string calibName;

		for (int i = 2; i < argc; ++i) 
		{
			std::string arg = argv[i];
			if ((arg == "-s" || arg == "--session") && i + 1 < argc) sessionPathStr = argv[++i];
			if ((arg == "-c" || arg == "--calibration") && i + 1 < argc) calibName = argv[++i];
		}

		if (sessionPathStr.empty())
		{
			Log::error("Error: set-calibration requires -s (session path).");
			logUsage(argv);
			return EXIT_FAILURE;
		}

		if (calibName.empty())
		{
			Log::error("Error: set-calibration requires -c (calibration name).");
			logUsage(argv);
			return EXIT_FAILURE;
		}

		try
		{
			Session session = loadSessionFromPath(sessionPathStr);
			session.setActiveCalibration(calibName);
		}
		catch (const std::exception& e)
		{
			Log::error("Error: ", e.what());
			return EXIT_FAILURE;
		}
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
		"  record           Record events to a calibration or scene capture\n",
		"  render           Process raw events into frames using E2VID\n",
		"  calibrate        Run Kalibr to compute camera intrinsics/extrinsics\n",
		"  set-calibration  Set the active calibration for a session\n",

		"record Options:\n",
		"  -p, --parent <dir>    (Required) Parent directory for session creation\n",
		"  -s, --session <name>  (Optional) Session name (prefix session_ is always added)\n",
		"                        Default: session_<timestamp>\n",
		"  -t, --type <type>     (Required) Capture type: 'calib' or 'scene'\n",
		"  -n, --name <name>     (Optional) Custom capture name (default: auto-generated)\n",
		"  -v, --visualize       (Optional) Enable live preview window\n\n",

		"render Options:\n",
		"  -s, --session <path>  (Required) Session directory path (must contain session.yaml)\n",
		"  -c, --capture <name>  (Required) Capture name (e.g., calib_01, scene_2024-01-26)\n\n",

		"calibrate Options:\n",
		"  -s, --session <path>  (Required) Session directory path (must contain session.yaml)\n",
		"  -c, --capture <name>  (Required) Calibration capture name (e.g., calib_01)\n",
		"  -t, --target <type>   (Optional*) Target type: 'aprilgrid', 'checkerboard', 'circlegrid'\n",
		"  --config <args>       (Optional*) Target configuration parameters\n",
		"                        *Required if no existing config in <session>/config/targets/\n\n",
		"    Target config arguments:\n",
		"    'aprilgrid':    <tagCols> <tagRows> <tagSize(m)> <tagSpacingRatio>\n",
		"    'checkerboard': <targetCols> <targetRows> <rowSpacing(m)> <colSpacing(m)>\n",
		"    'circlegrid':   <targetCols> <targetRows> <spacing(m)> <asymmetric(0/1)>\n\n",

		"set-calibration Options:\n",
		"  -s, --session <path>      (Required) Session directory path (must contain session.yaml)\n",
		"  -c, --calibration <name>  (Required) Calibration capture name to set as active\n\n",

		"Session Structure:\n",
		"  <session>/\n",
		"  ├── session.yaml              # Session metadata and active calibration\n",
		"  ├── config/\n",
		"  │   ├── targets/              # Calibration target definitions\n",
		"  │   └── esvo/                 # ESVO configuration files\n",
		"  ├── calibrations/             # Calibration captures\n",
		"  │   └── <name>/raw/, intermediate/, frames/, stereo_frames-camchain.yaml\n",
		"  ├── scenes/                   # Scene captures\n",
		"  │   └── <name>/raw/, intermediate/, frames/, reconstruction/esvo/\n",
		"  └── logs/                     # (planned) Session logs\n\n",

		"Examples:\n",
		"  ", cmd, " record -p . -s lab -t calib -n test\n",
		"  ", cmd, " render -s ./session_lab -c test\n",
		"  ", cmd, " calibrate -s ./session_lab -c test -t checkerboard --config 7 5 0.043 0.043\n",
		"  ", cmd, " record -p ./data -s lab -t scene -n desk_test\n",
		"  ", cmd, " set-calibration -s ./data/session_lab -c calib_01\n"
	);
}
