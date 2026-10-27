# TesserPack Regolith filter

A local [Regolith](https://bedrock-oss.github.io/regolith/) filter that runs [TesserPack](https://github.com/TBroz15/TesserPack) on staged Minecraft Bedrock behavior and resource packs. It preserves PNG files omitted by TesserPack 0.4.2 and restores each pack's `texts` directory after optimization.

This is a wrapper around TesserPack, not a fork or a fix to its executable.

## Installation

Clone this repository:

```sh
git clone https://github.com/alexdev03/tesserpack-regolith.git
```

Copy `tesserpack-regolith/filters/tesserpack` into the `filters` directory of your Regolith project. Then add the filter definition and the filter to the desired profile in your project's `config.json`:

```json
{
  "regolith": {
    "filterDefinitions": {
      "tesserpack": {
        "runWith": "python",
        "script": "./filters/tesserpack/__main__.py"
      }
    },
    "profiles": {
      "build-release": {
        "filters": [
          { "filter": "tesserpack", "settings": { "version": "0.4.2" } }
        ]
      }
    }
  }
}
```

Merge these entries into your existing configuration; place the filter after template and script generation and before packing. Run your configured profile with `regolith run build-release`.

The filter needs Python 3.9 or newer and supports Windows and Linux x86-64. On first use it downloads the selected TesserPack release into `tools/tesserpack/bin-<version>` in the project. Linux also requires TesserPack's native libraries; see the upstream documentation. `settings.json` supplies the default version, which profile settings can override.

## Behavior and limitations

- Each staged `BP` and `RP` is compiled separately. Missing PNGs are copied from the input into the optimized archive; already optimized PNGs are retained.
- The original `texts` directory is restored to avoid missing language files.
- On Linux, a compilation failure logs a warning and leaves that pack unoptimized. On Windows, it stops the filter.
- Other file types are not automatically restored if TesserPack omits them. Check the resulting pack and test it in Minecraft before release.
- The filter replaces the contents of the staged packs, so use it only within Regolith's staging directory.

## Test

```sh
python filters/tesserpack/test_tesserpack.py
```

The test checks that a missing PNG is restored and an optimized PNG is retained.
