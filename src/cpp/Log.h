#pragma once
#include <iostream>

enum LogLevel
{
	INFO,
	WARN,
	ERROR,
};

// use inline here for linker to merges duplicates 
inline LogLevel GLOBAL_LOG_LEVEL = LogLevel::INFO;

class Log
{
	public:
		template<typename... Args>
		static void info(const Args&... args)
		{
			if (LogLevel::INFO >= GLOBAL_LOG_LEVEL)
			{
				std::cout << "[INFO]  | ";
				((std::cout << args),...);
				std::cout << std::endl;
			}
		}

		template<typename... Args>
		static void warn(const Args&... args)
		{
			if (LogLevel::WARN >= GLOBAL_LOG_LEVEL)
			{
				std::cout << "[WARN]  | ";
				((std::cout << args),...);
				std::cout << std::endl;
			}
		}

		template<typename... Args>
		static void error(const Args&... args)
		{
			if (LogLevel::ERROR >= GLOBAL_LOG_LEVEL)
			{
				std::cerr << "[ERROR] | ";
				((std::cerr << args),...);
				std::cerr << std::endl;
			}
		}
};
