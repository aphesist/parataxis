# provenance

these files are copied unchanged from contraprova (github.com/aphesist/contraprova) at commit
`403caf23e1f9321e0244f3805b00a177476df4e0`, path `results/swepro-lanes/`. contraprova produced them:
its harness ran the probe and the main study, with contraprova's frozen copy of the lane layer.
they are parataxis's starting evidence, not a parataxis run.

- **pre-registration hashes refer to contraprova paths.** `PREREG.md` and `PREREG-probe.md` freeze
  sha256 hashes of files such as `src/contraprova/harness/lanes.py`. those hashes hold for
  contraprova at the commit above, which keeps its frozen copy. they do not describe
  `src/parataxis/lanes.py`: that file adds absolute imports and a module-routing hook, so its hash
  differs. the lane logic itself is unchanged at the time of the move. checked when copied:
  contraprova's `lanes.py` (`38b1b874…`) and `lanes_detect.py` (`bc28406c…`) at that commit match
  the hashes in `PREREG.md`.
- **commands in the readmes are contraprova commands** (`python -m contraprova.harness.run ...`,
  `contraprova verify`, `contraprova report --lanes`). they run with the pinned dependency.
- **commit hashes cited inside these files** (for example 1ed672e, the pre-registration commit) are
  contraprova commits.
- **no task data.** the logs hold `contents_sha256` fields, not repository file contents, as in
  contraprova.

## files (sha256)

- `PREREG-probe.md`: `621ec540b3ece6d7dbf411b92542a9343436ad910a7a621444f90c46f22b569a`
- `PREREG.md`: `67bb10ae6282f34704dde6d93bfc2274980428e249ead2011c9aa0706c3da318`
- `main/README.md`: `5cc4728dd092f3b517068e80d1521c0d0386b0e6167d88188bb9ac9196060f33`
- `main/analysis.json`: `d04ff74150c8e41cc3a6d00cf9a248fd01fab62c99dbf503274ff9b2a4abdf1f`
- `main/log.jsonl`: `9c21ba699a1b5ebb18f52051237fd87f8c01b101037bd8939aa190738bc9cca9`
- `main/log.validation.jsonl`: `4cf8d7b2446251be191b5d3fe86dc8af825a7e55ee19064194ebddbbbc3ee689`
- `main/preflight.json`: `8f0c56a74e4f024fdf7c92935816d6f12d5ec65e393c00ca852c76fb8da9331b`
- `main/report.md`: `aed06c128e1553e1a4974136224b2b48271b350f2d5dbfc8bab17fbd690cf3d5`
- `main/summary.json`: `5118fed18a3d80cded6d87b3282f02d191f1e1ae46bd2ef2f586845845fd2736`
- `probe/README.md`: `79037b7a10516ad52dd01a052308c1103b0a413de9180cd83ce538ccdefb8076`
- `probe/log.jsonl`: `881a030b17d09bc690f6335cc5bf6896bacee8036f8907e5e6e6403de9bca519`
- `probe/log.validation.jsonl`: `b53fddf76ab93b46bc2d375318d5f8f2abdf122a40ea68deb5a0abd477f18b30`
- `probe/main-estimate-preflight.json`: `5ba262dc7d5ba9e5e7546f97d982e9052d43678ba1e293e6819dbefe73abc753`
- `probe/preflight.json`: `75294e0868d1949ba7ca253a354e9ced8e03f81ccdde2a47c663186aad5207fe`
- `probe/report.md`: `2d63aefa20e80bd2eea55e74bbea063e73d45750f091b8d2e4ec087040ff535a`
- `probe/summary.json`: `d88ad0b65c779d9b29ba2c85e144411c13b429eebd3382747c9840334763ab7f`
- `splits.json`: `66847506882f7bcd511f828797844b05ec1fdc69220dee92e7620f0b24b1c88d`
- `validate-lanes.json`: `3e614520ad7abd0a83cb3e67ba875b4200ed3971c106eadb930baffe7a273a12`
