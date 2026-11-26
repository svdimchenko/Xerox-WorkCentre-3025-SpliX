# Xerox WorkCentre 3025 driver for macOS (SpliX-based)
#
#   make            build filter + PPD
#   make test       run the full CUPS pipeline offline and validate the output
#   make pkg        build an installer package in build/
#   make install    install directly (sudo)
#   make uninstall  remove everything this driver installed (sudo)

VERSION        := 0.0.1
SPLIX_VERSION  := 2.0.2+7a80218
PKG_ID         := io.github.splix.wc3025

# Install locations. /usr/libexec/cups is SIP-protected on macOS, so the
# filter lives under /Library/Printers and the PPD references it by full path.
PREFIX_DIR     := /Library/Printers/SpliX
FILTER_DIR     := $(PREFIX_DIR)/Filters
PPD_DIR        := /Library/Printers/PPDs/Contents/Resources
PPD_NAME       := Xerox WorkCentre 3025 SpliX.ppd.gz

SPLIX          := vendor/splix
BUILD          := build

ARCHS          := -arch arm64 -arch x86_64
MIN_MACOS      := 11.0
CXX            := clang++
CXXFLAGS       := -std=c++11 -O2 $(ARCHS) -mmacosx-version-min=$(MIN_MACOS) \
                  -I$(SPLIX)/include -DDISABLE_JBIG -DTHREADS=2 -DCACHESIZE=30 \
                  -Wall -Wno-deprecated-declarations -Wno-missing-braces
LDLIBS         := -lcups -lcupsimage

SRCS           := $(wildcard $(SPLIX)/src/*.cpp)
OBJS           := $(patsubst $(SPLIX)/src/%.cpp,$(BUILD)/obj/%.o,$(SRCS))

FILTER         := $(BUILD)/rastertoqpdl
PPD            := $(BUILD)/wc3025.ppd
PKG            := $(BUILD)/Xerox-WorkCentre-3025-SpliX-$(VERSION).pkg

.PHONY: all test pkg install uninstall clean

all: $(FILTER) $(PPD)

$(BUILD)/obj/%.o: $(SPLIX)/src/%.cpp $(wildcard $(SPLIX)/include/*.h)
	@mkdir -p $(@D)
	$(CXX) $(CXXFLAGS) -c $< -o $@

$(FILTER): $(OBJS)
	$(CXX) $(ARCHS) -mmacosx-version-min=$(MIN_MACOS) $^ $(LDLIBS) -o $@
	codesign --force --sign - $@

# PPD: expand SpliX's #import directives, compile with ppdc, keep only the
# WC3025 PPD, then patch it for a macOS install (see tools/patch-ppd.sh).
$(PPD): $(wildcard $(SPLIX)/ppd/*) tools/expand-drv.sh tools/patch-ppd.sh
	@mkdir -p $(BUILD)/ppdc
	tools/expand-drv.sh $(SPLIX)/ppd/xerox.drv.in > $(BUILD)/ppdc/xerox.drv
	cd $(SPLIX)/ppd && ppdc -I . -d $(abspath $(BUILD)/ppdc) $(abspath $(BUILD)/ppdc/xerox.drv)
	tools/patch-ppd.sh "$(FILTER_DIR)/rastertoqpdl" "$(VERSION)" \
		< $(BUILD)/ppdc/wc3025.ppd > $@
	cupstestppd -W filters -W translations $@ >/dev/null || \
		{ cupstestppd -W filters -W translations $@; exit 1; }

test: all
	tools/test-pipeline.sh $(FILTER) $(PPD)

pkg: $(PKG)

$(PKG): $(FILTER) $(PPD)
	rm -rf $(BUILD)/root
	install -d $(BUILD)/root$(FILTER_DIR) $(BUILD)/root$(PPD_DIR)
	install -m 755 $(FILTER) $(BUILD)/root$(FILTER_DIR)/rastertoqpdl
	install -m 644 $(SPLIX)/COPYING $(BUILD)/root$(PREFIX_DIR)/COPYING
	gzip -9 -n -c $(PPD) > "$(BUILD)/root$(PPD_DIR)/$(PPD_NAME)"
	chmod 644 "$(BUILD)/root$(PPD_DIR)/$(PPD_NAME)"
	pkgbuild --root $(BUILD)/root --identifier $(PKG_ID) --version $(VERSION) \
		--install-location / --ownership recommended $@

install: $(PKG)
	sudo installer -pkg $(PKG) -target /

uninstall:
	sudo tools/uninstall.sh

clean:
	rm -rf $(BUILD)
