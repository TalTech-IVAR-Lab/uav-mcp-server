#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>
#include <thread>
#include <vector>

#include <opencv2/opencv.hpp>

#include <gazebo/gazebo_client.hh>
#include <gazebo/msgs/msgs.hh>
#include <gazebo/transport/transport.hh>

namespace {

constexpr std::uint32_t kPixelFormatLInt8 = 1;
constexpr std::uint32_t kPixelFormatRgbInt8 = 3;
constexpr std::uint32_t kPixelFormatBgrInt8 = 8;

class Bridge {
public:
  explicit Bridge(std::string topic) : topic_(std::move(topic)) {}

  int Run() {
    gazebo::client::setup();

    gazebo::transport::NodePtr node(new gazebo::transport::Node());
    node->Init();

    subscriber_ = node->Subscribe(topic_, &Bridge::OnImage, this);
    if (!subscriber_) {
      std::cerr << "Failed to subscribe to Gazebo topic " << topic_ << std::endl;
      gazebo::client::shutdown();
      return 1;
    }

    std::cerr << "Subscribed to Gazebo camera topic " << topic_ << std::endl;

    while (running_.load()) {
      std::this_thread::sleep_for(std::chrono::milliseconds(200));
    }

    gazebo::client::shutdown();
    return 0;
  }

private:
  void OnImage(const boost::shared_ptr<const gazebo::msgs::ImageStamped> &message) {
    const auto &image = message->image();
    const auto width = static_cast<int>(image.width());
    const auto height = static_cast<int>(image.height());

    if (width <= 0 || height <= 0 || image.data().empty()) {
      return;
    }

    cv::Mat frame;
    if (image.pixel_format() == kPixelFormatRgbInt8) {
      cv::Mat rgb(height, width, CV_8UC3,
                  const_cast<char *>(image.data().data()));
      cv::cvtColor(rgb, frame, cv::COLOR_RGB2BGR);
    } else if (image.pixel_format() == kPixelFormatBgrInt8) {
      frame = cv::Mat(height, width, CV_8UC3,
                      const_cast<char *>(image.data().data())).clone();
    } else if (image.pixel_format() == kPixelFormatLInt8) {
      cv::Mat mono(height, width, CV_8UC1,
                   const_cast<char *>(image.data().data()));
      cv::cvtColor(mono, frame, cv::COLOR_GRAY2BGR);
    } else {
      return;
    }

    std::vector<unsigned char> encoded;
    if (!cv::imencode(".jpg", frame, encoded,
                      {cv::IMWRITE_JPEG_QUALITY, 85})) {
      return;
    }

    const std::uint32_t length = static_cast<std::uint32_t>(encoded.size());
    const unsigned char header[4] = {
        static_cast<unsigned char>((length >> 24) & 0xFFu),
        static_cast<unsigned char>((length >> 16) & 0xFFu),
        static_cast<unsigned char>((length >> 8) & 0xFFu),
        static_cast<unsigned char>(length & 0xFFu),
    };

    std::cout.write(reinterpret_cast<const char *>(header), sizeof(header));
    std::cout.write(reinterpret_cast<const char *>(encoded.data()),
                    static_cast<std::streamsize>(encoded.size()));
    std::cout.flush();
  }

  std::string topic_;
  std::atomic<bool> running_{true};
  gazebo::transport::SubscriberPtr subscriber_;
};

}  // namespace

int main(int argc, char **argv) {
  std::string topic;

  for (int i = 1; i < argc; ++i) {
    if (std::strcmp(argv[i], "--topic") == 0 && i + 1 < argc) {
      topic = argv[++i];
      continue;
    }
  }

  if (topic.empty()) {
    std::cerr << "Usage: gazebo_camera_bridge --topic <gazebo-topic>" << std::endl;
    return 2;
  }

  return Bridge(topic).Run();
}
