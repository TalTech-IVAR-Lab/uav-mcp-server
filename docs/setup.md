# Setup Notes

## Preferred environment

- Ubuntu 24.04 LTS
- Native PX4 SITL build
- Python 3.12

## Initial setup plan

1. Install PX4 dependencies with the official Ubuntu setup script.
2. Build and start PX4 SITL with `gz_x500`.
3. Create a Python virtual environment.
4. Install the package in editable mode with development dependencies.
5. Verify MAVSDK can connect to UDP port `14540`.

## Notes

- Docker is acceptable for reproducibility, but native Linux is the preferred development path.
- Camera-dependent work should stay out of the critical path until the core system is stable.

