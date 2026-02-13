#pragma once
#include <filesystem>
#include <string>
#include <optional>

enum class CaptureType
{
	CALIBRATION,
	SCENE
};

class Session
{
public:
	static Session create(const std::filesystem::path& parentPath, const std::string& name);
	
	static Session load(const std::filesystem::path& sessionPath);
	
	static bool isValidSession(const std::filesystem::path& path);
	static std::filesystem::path findSessionRoot(const std::filesystem::path& startPath);

	std::filesystem::path getPath() const { return rootPath_; }
	std::filesystem::path getConfigDir() const { return rootPath_ / "config"; }
	std::filesystem::path getTargetsDir() const { return rootPath_ / "config" / "targets"; }
	std::filesystem::path getCalibrationsDir() const { return rootPath_ / "calibrations"; }
	std::filesystem::path getScenesDir() const { return rootPath_ / "scenes"; }
	std::filesystem::path getLogsDir() const { return rootPath_ / "logs"; }

	std::string nextCalibrationName() const;
	std::string generateSceneName() const;
	
	std::filesystem::path createCapture(CaptureType type, const std::string& name = "");
	std::filesystem::path getCaptureDir(const std::string& captureName) const;
	
	static std::filesystem::path getRawDir(const std::filesystem::path& captureDir);
	static std::filesystem::path getIntermediateDir(const std::filesystem::path& captureDir);
	static std::filesystem::path getFramesDir(const std::filesystem::path& captureDir);
	static std::filesystem::path getReconstructionDir(const std::filesystem::path& captureDir);  // 3D reconstruction parent (scenes only)
	static std::filesystem::path getEsvoDir(const std::filesystem::path& captureDir);            // reconstruction/esvo/ (scenes only)

	// active calibration management
	std::optional<std::string> getActiveCalibration() const;
	void setActiveCalibration(const std::string& calibName);
	std::filesystem::path getActiveCamchainPath() const;
	bool hasActiveCalibration() const;

	void setCameraInfo(const std::string& leftCam, const std::string& rightCam);
	std::string getLeftCamera() const;
	std::string getRightCamera() const;

	std::string getName() const;

	// save session.yaml
	void save();

private:
	Session() = default;
	void initializeDirectories();
	void loadConfig();

	std::filesystem::path rootPath_;
	std::string name_;
	std::string created_;
	std::optional<std::string> activeCalibration_;
	std::string leftCamera_;
	std::string rightCamera_;
	std::string notes_;
};
