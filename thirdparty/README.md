# Third-Party Dependencies

This directory contains scripts for downloading and building third-party
dependencies for Gaius. Following the [Apache Kudu](https://github.com/apache/kudu/tree/master/thirdparty)
pattern for thirdparty management.

## Directory Structure

```
thirdparty/
├── README.md              # This file
├── LICENSE.txt            # Aggregated licenses for third-party code
├── vars.sh                # Version pins and configuration
├── download-thirdparty.sh # Downloads source code
├── build-thirdparty.sh    # Builds from source
│
├── src/                   # Downloaded source code (gitignored)
│   └── cm_ext/            # Cloudera Manager Extension Tools
│
├── build/                 # Build artifacts (gitignored)
│
├── installed/             # Final installed artifacts (gitignored)
│   └── cloudera/
│       └── validator.jar  # Cloudera parcel/CSD validator
│
├── cloudera/              # Cloudera-specific scripts and configs
│
└── patches/               # Patches for third-party code
```

## Quick Start

```bash
# Download all dependencies
./download-thirdparty.sh

# Build all dependencies
./build-thirdparty.sh
```

## Prerequisites

- **Java JDK 8+** - Required for building cm_ext
- **Maven 3.6+** - Build tool for Java projects
- **Git** - For cloning repositories

## Components

### Cloudera Manager Extension Tools (cm_ext)

The [cm_ext](https://github.com/cloudera/cm_ext) toolkit provides:

- **validator.jar** - Validates parcel and CSD metadata files
- Schema definitions for Cloudera Manager extensions
- Documentation for building custom parcels

#### Usage

After building, validate a parcel:

```bash
java -jar installed/cloudera/validator.jar -f path/to/GAIUS_ENGINE-1.0.0-el8.parcel
```

Validate a CSD file:

```bash
java -jar installed/cloudera/validator.jar -s path/to/GAIUS_ENGINE.sdl
```

#### Why We Need This

Gaius Engine can be deployed as a Cloudera Parcel for integration with
Cloudera Data Platform (CDP). The validator ensures our parcel metadata
is correct before deployment to customer environments.

## Building Individual Components

```bash
# Download and build only cm_ext
./download-thirdparty.sh --component cm_ext
./build-thirdparty.sh --component cm_ext
```

## Updating Dependencies

1. Edit `vars.sh` to update version pins
2. Run `./download-thirdparty.sh` to fetch new versions
3. Run `./build-thirdparty.sh` to rebuild
4. Test the new artifacts
5. Commit the updated `vars.sh`

## License Information

See [LICENSE.txt](LICENSE.txt) for licensing information for all
third-party dependencies included in this directory.

The `src/`, `build/`, and `installed/` directories are gitignored as they
contain downloaded and built artifacts that should not be checked in.
