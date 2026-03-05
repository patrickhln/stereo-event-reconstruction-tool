#pragma once
#include <filesystem>
#include <string>
#include <vector>

namespace FrameGen
{
	struct CameraMetadata
	{
		std::string leftCamName, rightCamName;
	};

	struct RenderOptions
	{
		std::string model = "e2vid";
		std::string device = "auto";
		std::vector<std::string> extraArgs;
	};
	int environment_installed(); 
	int convertAedat4ToTxt(const std::filesystem::path& inputAedat4, const std::filesystem::path& outputDir, const std::string& leftCamName, const std::string& rightCamName); 
	int runE2VID(const std::filesystem::path& eventFile, const std::filesystem::path& outputDir, const std::string& datasetName, const RenderOptions& options);
	int runECNN(const std::filesystem::path& txtFile, const std::filesystem::path& outputDir, const std::string& datasetName, const RenderOptions& options);
	int recordingToVideo(const std::filesystem::path& intermediateDir, const std::filesystem::path& reconstructionDir, const RenderOptions& options);
	CameraMetadata readMetadata(const std::filesystem::path& directory);
	
}
