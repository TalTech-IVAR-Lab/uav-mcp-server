// Gazebo Harmonic (gz-transport13) camera bridge.
// Subscribes to a gz::msgs::Image topic and writes length-prefixed JPEG frames
// to stdout, matching the protocol expected by camera.py.
#include <chrono>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>
#include <thread>
#include <vector>

#include <opencv2/opencv.hpp>
#include <gz/msgs/image.pb.h>
#include <gz/transport/Node.hh>

static void WriteFrame(const cv::Mat &bgr) {
    std::vector<unsigned char> encoded;
    if (!cv::imencode(".jpg", bgr, encoded, {cv::IMWRITE_JPEG_QUALITY, 85}))
        return;
    const auto len = static_cast<std::uint32_t>(encoded.size());
    const unsigned char header[4] = {
        static_cast<unsigned char>((len >> 24) & 0xFFu),
        static_cast<unsigned char>((len >> 16) & 0xFFu),
        static_cast<unsigned char>((len >>  8) & 0xFFu),
        static_cast<unsigned char>( len        & 0xFFu),
    };
    std::cout.write(reinterpret_cast<const char *>(header), 4);
    std::cout.write(reinterpret_cast<const char *>(encoded.data()),
                    static_cast<std::streamsize>(encoded.size()));
    std::cout.flush();
}

static void OnImage(const gz::msgs::Image &msg) {
    const int w = static_cast<int>(msg.width());
    const int h = static_cast<int>(msg.height());
    if (w <= 0 || h <= 0 || msg.data().empty())
        return;

    cv::Mat frame;
    const auto fmt = msg.pixel_format_type();
    if (fmt == gz::msgs::PixelFormatType::RGB_INT8) {
        cv::Mat rgb(h, w, CV_8UC3, const_cast<char *>(msg.data().data()));
        cv::cvtColor(rgb, frame, cv::COLOR_RGB2BGR);
    } else if (fmt == gz::msgs::PixelFormatType::BGR_INT8) {
        frame = cv::Mat(h, w, CV_8UC3, const_cast<char *>(msg.data().data())).clone();
    } else if (fmt == gz::msgs::PixelFormatType::L_INT8) {
        cv::Mat mono(h, w, CV_8UC1, const_cast<char *>(msg.data().data()));
        cv::cvtColor(mono, frame, cv::COLOR_GRAY2BGR);
    } else {
        return;
    }
    WriteFrame(frame);
}

int main(int argc, char **argv) {
    std::string topic;
    for (int i = 1; i < argc; ++i) {
        if (std::strcmp(argv[i], "--topic") == 0 && i + 1 < argc)
            topic = argv[++i];
    }
    if (topic.empty()) {
        std::cerr << "Usage: gz_camera_bridge --topic <gz-topic>" << std::endl;
        return 2;
    }

    gz::transport::Node node;
    if (!node.Subscribe(topic, &OnImage)) {
        std::cerr << "Failed to subscribe to gz topic " << topic << std::endl;
        return 1;
    }
    std::cerr << "Subscribed to gz camera topic " << topic << std::endl;

    gz::transport::waitForShutdown();
    return 0;
}
