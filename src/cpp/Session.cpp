#include "Session.h"
#include "Log.h"

#include <yaml-cpp/yaml.h>
#include <fstream>
#include <chrono>
#include <iomanip>
#include <sstream>
#include <regex>

// example: 2026-02-02_13-01-01
static std::string getCurrentTimestamp()
{
	auto now = std::chrono::system_clock::now();
	auto in_time_t = std::chrono::system_clock::to_time_t(now);
	std::stringstream ss;
	ss << std::put_time(std::localtime(&in_time_t), "%Y-%m-%d_%H-%M-%S");
	return ss.str();
}
// example (uses T seperator) 2026-02-02T13:01:01Z
static std::string getISOTimestamp()
{
	auto now = std::chrono::system_clock::now();
	auto in_time_t = std::chrono::system_clock::to_time_t(now);
	std::stringstream ss;
	ss << std::put_time(std::gmtime(&in_time_t), "%Y-%m-%dT%H:%M:%SZ");
	return ss.str();
}

static void writeFileIfMissing(const std::filesystem::path &path, const std::string &content)
{
	if (std::filesystem::exists(path))
	{
		return;
	}

	std::ofstream file(path);
	if (!file.is_open())
	{
		throw std::runtime_error("Could not create file: " + path.string());
	}
	file << content;
}

Session Session::create(const std::filesystem::path& parentPath, const std::string& name)
{
	Session session;
	
	std::string sessionName = name.empty() ? getCurrentTimestamp() : name;
	session.rootPath_ = parentPath / sessionName;
	session.name_ = sessionName;
	session.created_ = getISOTimestamp();
	session.activeCalibration_ = std::nullopt;
	
	session.initializeDirectories();
	session.save();
	
	Log::info("Created session: ", session.rootPath_.string());
	return session;
}

Session Session::load(const std::filesystem::path& sessionPath)
{
	Session session;
	session.rootPath_ = sessionPath;
	
	if (!isValidSession(sessionPath))
	{
		throw std::runtime_error("Invalid session path: " + sessionPath.string());
	}
	
	session.loadConfig();
	return session;
}

bool Session::isValidSession(const std::filesystem::path& path)
{
	// maybe make sure session.yaml also contains certain keywords
	return std::filesystem::exists(path / "session.yaml");
}

std::filesystem::path Session::findSessionRoot(const std::filesystem::path& startPath)
{
	std::filesystem::path current = std::filesystem::absolute(startPath);
	if (std::filesystem::is_regular_file(current))
		current = current.parent_path();
	
	while (!current.empty())
	{
		if (isValidSession(current))
			return current;
		auto parent = current.parent_path();
		if (parent == current) break;
		current = parent;
	}
	throw std::runtime_error("No session found in path hierarchy: " + startPath.string());
}

void Session::initializeDirectories()
{
	std::filesystem::create_directories(rootPath_);
	std::filesystem::create_directories(getConfigDir());
	std::filesystem::create_directories(getTargetsDir());
	std::filesystem::path filtersDir = getConfigDir() / "filters";
	std::filesystem::create_directories(filtersDir);
	std::filesystem::create_directories(getCalibrationsDir());
	std::filesystem::create_directories(getScenesDir());

	writeFileIfMissing(filtersDir / "hot_only.yaml", R"(chain:
  - type: hot_pixel

hot_pixel:
  auto_detect: true
  n_std_dev: 4.0
  n_hot_pixels: -1
)");

	writeFileIfMissing(filtersDir / "ba_only.yaml", R"(chain:
  - type: background_activity
    time_window_us: 3000
)");

	writeFileIfMissing(filtersDir / "hot_then_ba.yaml", R"(chain:
  - type: hot_pixel
  - type: background_activity
    time_window_us: 3000

hot_pixel:
  auto_detect: true
  n_std_dev: 4.0
  n_hot_pixels: -1
)");

	writeFileIfMissing(filtersDir / "ba_then_hot.yaml", R"(chain:
  - type: background_activity
    time_window_us: 3000
  - type: hot_pixel

hot_pixel:
  auto_detect: true
  n_std_dev: 4.0
  n_hot_pixels: -1
)");

	// logs/ created on-demand when logging is implemented
}

void Session::loadConfig()
{
	std::filesystem::path configPath = rootPath_ / "session.yaml";
	
	try
	{
		YAML::Node config = YAML::LoadFile(configPath.string());
		
		name_ = config["name"].as<std::string>("");
		created_ = config["created"].as<std::string>("");
		
		if (config["active_calibration"] && !config["active_calibration"].IsNull())
		{
			activeCalibration_ = config["active_calibration"].as<std::string>();
		}
		
		if (config["cameras"])
		{
			leftCamera_ = config["cameras"]["left"].as<std::string>("");
			rightCamera_ = config["cameras"]["right"].as<std::string>("");
		}
		
		notes_ = config["notes"].as<std::string>("");
	}
	catch (const YAML::Exception& e)
	{
		throw std::runtime_error("Failed to load session.yaml: " + std::string(e.what()));
	}
}

void Session::save()
{
	YAML::Emitter out;
	out << YAML::BeginMap;
	out << YAML::Key << "name" << YAML::Value << name_;
	out << YAML::Key << "created" << YAML::Value << created_;
	
	if (activeCalibration_.has_value())
	{
		out << YAML::Key << "active_calibration" << YAML::Value << activeCalibration_.value();
	}
	else
	{
		out << YAML::Key << "active_calibration" << YAML::Value << YAML::Null;
	}
	
	out << YAML::Key << "cameras" << YAML::Value << YAML::BeginMap;
	out << YAML::Key << "left" << YAML::Value << leftCamera_;
	out << YAML::Key << "right" << YAML::Value << rightCamera_;
	out << YAML::EndMap;
	
	out << YAML::Key << "notes" << YAML::Value << notes_;
	out << YAML::EndMap;
	
	std::filesystem::path configPath = rootPath_ / "session.yaml";
	std::ofstream fout(configPath);
	fout << out.c_str();
	fout.close();
}

std::string Session::nextCalibrationName() const
{
	int maxNum = 0;
	std::regex calibPattern("calib_(\\d+)");
	
	if (std::filesystem::exists(getCalibrationsDir()))
	{
		for (const auto& entry : std::filesystem::directory_iterator(getCalibrationsDir()))
		{
			if (entry.is_directory())
			{
				std::string dirName = entry.path().filename().string();
				std::smatch match;
				if (std::regex_match(dirName, match, calibPattern))
				{
					int num = std::stoi(match[1].str());
					if (num > maxNum) maxNum = num;
				}
			}
		}
	}
	
	std::stringstream ss;
	ss << "calib_" << std::setfill('0') << std::setw(2) << (maxNum + 1);
	return ss.str();
}

std::string Session::generateSceneName() const
{
	return "scene_" + getCurrentTimestamp();
}

std::filesystem::path Session::createCapture(CaptureType type, const std::string& name)
{
	std::filesystem::path captureDir;
	std::string captureName;
	
	if (type == CaptureType::CALIBRATION)
	{
		captureName = name.empty() ? nextCalibrationName() : name;
		captureDir = getCalibrationsDir() / captureName;
	}
	else
	{
		captureName = name.empty() ? generateSceneName() : name;
		captureDir = getScenesDir() / captureName;
	}
	
	std::filesystem::create_directories(getRawDir(captureDir));
	std::filesystem::create_directories(getIntermediateDir(captureDir));
	std::filesystem::create_directories(getFramesDir(captureDir));
	
	if (type == CaptureType::SCENE)
	{
		// Scenes get a reconstruction folder for 3D methods
		std::filesystem::create_directories(getReconstructionDir(captureDir));
	}
	
	Log::info("Created capture: ", captureDir.string());
	return captureDir;
}

std::filesystem::path Session::getCaptureDir(const std::string& captureName) const
{
	// Check in calibrations first
	std::filesystem::path calibPath = getCalibrationsDir() / captureName;
	if (std::filesystem::exists(calibPath))
	{
		return calibPath;
	}
	
	// Then check in scenes
	std::filesystem::path scenePath = getScenesDir() / captureName;
	if (std::filesystem::exists(scenePath))
	{
		return scenePath;
	}
	
	throw std::runtime_error("Capture not found: " + captureName);
}

std::filesystem::path Session::getRawDir(const std::filesystem::path& captureDir)
{
	return captureDir / "raw";
}

std::filesystem::path Session::getIntermediateDir(const std::filesystem::path& captureDir)
{
	return captureDir / "intermediate";
}

std::filesystem::path Session::getFramesDir(const std::filesystem::path& captureDir)
{
	return captureDir / "frames";
}

std::filesystem::path Session::getReconstructionDir(const std::filesystem::path& captureDir)
{
	return captureDir / "reconstruction";
}

std::filesystem::path Session::getEsvoDir(const std::filesystem::path& captureDir)
{
	return captureDir / "reconstruction" / "esvo";
}

std::optional<std::string> Session::getActiveCalibration() const
{
	return activeCalibration_;
}

void Session::setActiveCalibration(const std::string& calibName)
{
	// Verify the calibration exists and has stereo_frames-camchain.yaml
	std::filesystem::path calibDir = getCalibrationsDir() / calibName;
	std::filesystem::path camchainPath = calibDir / "stereo_frames-camchain.yaml";
	
	if (!std::filesystem::exists(calibDir))
	{
		throw std::runtime_error("Calibration does not exist: " + calibName);
	}
	if (!std::filesystem::exists(camchainPath))
	{
		throw std::runtime_error("Calibration has no stereo_frames-camchain.yaml: " + calibName);
	}
	
	activeCalibration_ = calibName;
	save();
	
	Log::info("Set active calibration to: ", calibName);
}

std::filesystem::path Session::getActiveCamchainPath() const
{
	if (!activeCalibration_.has_value())
	{
		throw std::runtime_error("No active calibration set");
	}
	std::filesystem::path calibDir = getCalibrationsDir() / activeCalibration_.value();
	std::filesystem::path camchainPath = calibDir / "stereo_frames-camchain.yaml";
	if (std::filesystem::exists(camchainPath))
	{
		return camchainPath;
	}
	throw std::runtime_error("Active calibration has no camchain file: " + activeCalibration_.value());
}

bool Session::hasActiveCalibration() const
{
	return activeCalibration_.has_value();
}

void Session::setCameraInfo(const std::string& leftCam, const std::string& rightCam)
{
	leftCamera_ = leftCam;
	rightCamera_ = rightCam;
	save();
}

std::string Session::getLeftCamera() const
{
	return leftCamera_;
}

std::string Session::getRightCamera() const
{
	return rightCamera_;
}

std::string Session::getName() const
{
	return name_;
}
