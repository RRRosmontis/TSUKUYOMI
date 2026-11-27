.PHONY: default all _default install help clean destroy server utest _prepare_dir  srs_mp4_parser srs_hls_ingester
.PHONY: clean_srs clean_modules clean_openssl clean_srtp2 clean_opus clean_ffmpeg clean_st
.PHONY: st ffmpeg

GCC = gcc
CXX = g++
AR = ar
LINK = ld
RANDLIB = randlib
CXXFLAGS =  -std=c++11 -Wall -g -O0 -fsanitize=address -fno-omit-frame-pointer
LDFLAGS = 

# install prefix.
SRS_PREFIX=/usr/local/srs
SRS_DEFAULT_CONFIG=conf/srs.conf
__REAL_INSTALL=$(DESTDIR)$(SRS_PREFIX)

SRS_FORCE_MAKE_JOBS=YES
JOBS=$(shell echo $(MAKEFLAGS)| grep -qE '\-j[0-9]+' || echo " --jobs=2")

default: server

all: _default

_default: server utest  srs_mp4_parser srs_hls_ingester

help:
	@echo "Usage: make <help>|<clean>|<destroy>|<server>|<utest>|<install>|<uninstall>"
	@echo "     help            Display this help menu"
	@echo "     clean           Cleanup project and all depends"
	@echo "     destroy         Cleanup all files for this platform in ./objs/Platform-SRS6-Linux-5.15.0-GCC11.4.0-x86_64"
	@echo "     server          Build the srs and other modules in main"
	@echo "     utest           Build the utest for srs"
	@echo "     install         Install srs to the prefix path"
	@echo "     uninstall       Uninstall srs from prefix path"
	@echo "To rebuild special module:"
	@echo "     st              Rebuild st-srs in ./objs/Platform-SRS6-Linux-5.15.0-GCC11.4.0-x86_64/st-srs"
	@echo "     ffmpeg          Rebuild ffmpeg in ./objs/Platform-SRS6-Linux-5.15.0-GCC11.4.0-x86_64/ffmpeg-4.2-fit"
	@echo "To reconfigure special depends:"
	@echo "     clean_openssl   Remove the openssl cache."
	@echo "     clean_srtp2     Remove the libsrtp2 cache."
	@echo "     clean_opus      Remove the opus cache."
	@echo "     clean_ffmpeg    Remove the FFmpeg cache."
	@echo "     clean_st        Remove the ST cache."
	@echo "For example:"
	@echo "     make"
	@echo "     make help"

doclean:
	(cd ./objs && rm -rf srs srs_utest srs.exe srs_utest.exe  srs_mp4_parser srs_hls_ingester)
	(cd ./objs && rm -rf src/* include lib)
	(mkdir -p ./objs/utest && cd ./objs/utest && rm -rf *.o *.a)

clean: clean_srs clean_modules

destroy:
	(cd ./objs && rm -rf Platform-SRS6-Linux-5.15.0-GCC11.4.0-x86_64)

clean_srs:
	@(cd ./objs && rm -rf srs srs_utest src/* utest/*)

clean_modules:
	@(cd ./objs && rm -rf  srs_mp4_parser srs_hls_ingester)

clean_openssl:
	@rm -rf ./objs/Platform-SRS6-Linux-5.15.0-GCC11.4.0-x86_64/3rdparty/openssl
	@echo "Please rebuild openssl by: ./configure"

clean_srtp2:
	@rm -rf ./objs/Platform-SRS6-Linux-5.15.0-GCC11.4.0-x86_64/3rdparty/srtp2
	@echo "Please rebuild libsrtp2 by: ./configure"

clean_opus:
	@rm -rf ./objs/Platform-SRS6-Linux-5.15.0-GCC11.4.0-x86_64/3rdparty/opus
	@echo "Please rebuild opus by: ./configure"

clean_ffmpeg:
	@rm -rf ./objs/Platform-SRS6-Linux-5.15.0-GCC11.4.0-x86_64/3rdparty/ffmpeg
	@echo "Please rebuild FFmpeg by: ./configure"

clean_st:
	@rm -rf ./objs/Platform-SRS6-Linux-5.15.0-GCC11.4.0-x86_64/3rdparty/st
	@echo "Please rebuild ST by: ./configure"

st:
	@rm -f ./objs/srs srs_utest
	@$(MAKE)$(JOBS) -C ./objs/Platform-SRS6-Linux-5.15.0-GCC11.4.0-x86_64/st-srs clean
	@env EXTRA_CFLAGS="-DMALLOC_STACK -DMD_HAVE_EPOLL" $(MAKE)$(JOBS) -C ./objs/Platform-SRS6-Linux-5.15.0-GCC11.4.0-x86_64/st-srs linux-debug STATIC_ONLY=yes CC=gcc AR=ar LD=ld RANDLIB=randlib CC=$(GCC) AR=$(AR) LD=$(LINK) RANDLIB=$(RANDLIB)
	@echo "Please rebuild srs by: make"

ffmpeg:
	@rm -f ./objs/srs srs_utest
	$(MAKE)$(JOBS) -C ./objs/Platform-SRS6-Linux-5.15.0-GCC11.4.0-x86_64/ffmpeg-4.2-fit
	$(MAKE)$(JOBS) -C ./objs/Platform-SRS6-Linux-5.15.0-GCC11.4.0-x86_64/ffmpeg-4.2-fit install-libs
	@echo "Please rebuild srs by: make"

server: _prepare_dir
	@echo "Build the SRS server, JOBS=${JOBS}, FORCE_MAKE_JOBS=YES"
	$(MAKE)$(JOBS) -f ./objs/Makefile srs
	@bash objs/_srs_build_summary.sh

srs_mp4_parser: _prepare_dir server
	@echo "Build the srs_mp4_parser over SRS"
	$(MAKE)$(JOBS) -f ./objs/Makefile srs_mp4_parser

srs_hls_ingester: _prepare_dir server
	@echo "Build the srs_hls_ingester over SRS"
	$(MAKE)$(JOBS) -f ./objs/Makefile srs_hls_ingester

uninstall:
	@echo "rmdir $(SRS_PREFIX)"
	@rm -rf $(SRS_PREFIX)

install:
	@echo "Now mkdir $(__REAL_INSTALL)"
	@mkdir -p $(__REAL_INSTALL)
	@echo "Now make the http root dir"
	@mkdir -p $(__REAL_INSTALL)/objs/nginx/html
	@cp -f research/index.html $(__REAL_INSTALL)/objs/nginx/html
	@cp -f research/favicon.ico $(__REAL_INSTALL)/objs/nginx/html
	@cp -Rf research/players $(__REAL_INSTALL)/objs/nginx/html/
	@cp -Rf research/console $(__REAL_INSTALL)/objs/nginx/html/
	@cp -Rf 3rdparty/signaling/www/demos $(__REAL_INSTALL)/objs/nginx/html/
	@echo "Now copy binary files"
	@mkdir -p $(__REAL_INSTALL)/objs
	@cp -f objs/srs $(__REAL_INSTALL)/objs
	@echo "Now copy srs conf files"
	@mkdir -p $(__REAL_INSTALL)/conf
	@cp -f conf/*.conf $(__REAL_INSTALL)/conf
	@cp -f conf/server.key conf/server.crt $(__REAL_INSTALL)/conf
	@echo "Now copy init.d script files"
	@mkdir -p $(__REAL_INSTALL)/etc/init.d
	@cp -f etc/init.d/srs $(__REAL_INSTALL)/etc/init.d
	@sed -i "s|^ROOT=.*|ROOT=\"$(SRS_PREFIX)\"|g" $(__REAL_INSTALL)/etc/init.d/srs
	@sed -i "s|^CONFIG=.*|CONFIG=\"$(SRS_DEFAULT_CONFIG)\"|g" $(__REAL_INSTALL)/etc/init.d/srs
	@echo "Now copy systemctl service files"
	@mkdir -p $(__REAL_INSTALL)/usr/lib/systemd/system
	@cp -f usr/lib/systemd/system/srs.service $(__REAL_INSTALL)/usr/lib/systemd/system/srs.service
	@echo ""
	@echo "@see: https://ossrs.net/lts/zh-cn/docs/v4/doc/service"

utest: server
	@echo "Ignore utest for it's disabled."

# the ./configure will generate it.
_prepare_dir:
	@mkdir -p ./objs
	@mkdir -p ./objs/src/core
	@mkdir -p ./objs/src/kernel
	@mkdir -p ./objs/src/protocol
	@mkdir -p ./objs/src/app
	@mkdir -p ./objs/src/main
	@mkdir -p ./objs/src/main
