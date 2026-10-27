# TesserPack Regolith filter

A [Regolith](https://bedrock-oss.github.io/regolith/) filter that runs [TesserPack](https://github.com/TBroz15/TesserPack) on staged Minecraft Bedrock behavior and resource packs. It preserves PNG files omitted by TesserPack 0.4.2 and restores each pack's `texts` directory after optimization.

This is a wrapper around TesserPack, not a fork or a fix to its executable.

## Installation

Add the filter to the `regolith.filterDefinitions` section of your project's `config.json`:

```json
"tesserpack": {
  "url": "github.com/alexdev03/tesserpack-regolith",
  "version": "0.2.0"
}
```

Add it to the desired profile's `filters` list after template and script generation and before packing:

```json
{
  "filter": "tesserpack",
  "settings": { "version": "0.4.2" }
}
```

Download the configured filters from the project directory, then run your profile:

```sh
regolith install-all
regolith run build-release
```

Replace `build-release` with your profile name. The filter version `0.2.0` is pinned independently of the TesserPack executable version in the settings.

The filter needs Python 3.9 or newer and supports Windows and Linux x86-64. On first use it downloads the selected TesserPack release into `tools/tesserpack/bin-<version>` in the project. Linux also requires TesserPack's native libraries; see the upstream documentation. `settings.json` supplies the default version, which profile settings can override.

## Behavior and limitations

- Each staged `BP` and `RP` is compiled separately. Missing PNGs are copied from the input into the optimized archive; already optimized PNGs are retained.
- The original `texts` directory is restored to avoid missing language files.
- On Linux, a compilation failure logs a warning and leaves that pack unoptimized. On Windows, it stops the filter.
- Other file types are not automatically restored if TesserPack omits them. Check the resulting pack and test it in Minecraft before release.
- The filter replaces the contents of the staged packs, so use it only within Regolith's staging directory.

## Test

```sh
python tesserpack/test_tesserpack.py
```

The test checks that a missing PNG is restored and an optimized PNG is retained.
