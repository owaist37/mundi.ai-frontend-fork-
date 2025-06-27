# Copyright (C) 2025 Bunting Labs, Inc.

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

FROM camptocamp/qgis-server:3.44-gdal3.10
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates gnupg git wget \
        libcairo2-dev libgles2-mesa-dev libgbm-dev \
        libuv1-dev libprotobuf-dev xvfb x11-utils dbus cmake \
        libpng-dev python3-dev python3-pip pkg-config \
        libgdal-dev libdbus-1-dev dbus \
    && apt-get install --reinstall -y qgis python3-qgis \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --break-system-packages -r requirements.txt

ENV XDG_RUNTIME_DIR=/tmp/xdg-runtime
RUN mkdir -p /tmp && chmod 777 /tmp
RUN mkdir -p "$XDG_RUNTIME_DIR" && chmod 700 "$XDG_RUNTIME_DIR"

ENV QT_QPA_PLATFORM=offscreen \
    QGIS_PREFIX_PATH=/usr \
    LANG=en_US.UTF-8 \
    PYTHONPATH="/app" \
    LD_LIBRARY_PATH=/usr/lib \
    GDAL_DATA=/usr/share/gdal \
    PROJ_LIB=/usr/share/proj \
    GDAL_DRIVER_PATH=/usr/lib/gdalplugins \
    GEOTIFF_CSV=/usr/share/gdal
WORKDIR /app
ENV DISPLAY=:99
RUN chmod 777 "$XDG_RUNTIME_DIR" && chmod 777 /tmp

COPY server.py .

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]

