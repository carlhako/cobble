// bedrock-protocol pulls in `raknet-native`, whose loader is only satisfied by a
// compiled binary. The package ships N-API prebuilt binaries under
// prebuilds/<platform>-<kernelMajor>-<arch>, but its path helper keys on the
// *running* kernel's major version, so on (say) Linux 6.x it fails to find the
// bundled linux-5-x64 binary. N-API binaries are ABI-stable across kernel and
// Node versions, so we just stage whichever <platform>-*-<arch> prebuild exists
// into build/Release/, where node `bindings` looks. No compiler required.
//
// If no prebuilt binary matches this platform/arch, we leave things alone and
// let raknet-native's own build path take over.
const fs = require('fs')
const path = require('path')

try {
  const base = path.dirname(require.resolve('raknet-native/package.json'))
  const target = path.join(base, 'build', 'Release', 'node-raknet.node')
  if (fs.existsSync(target)) {
    process.exit(0)
  }
  const prebuilds = path.join(base, 'prebuilds')
  const match = fs
    .readdirSync(prebuilds)
    .find((d) => d.startsWith(process.platform + '-') && d.endsWith('-' + process.arch))
  if (!match) {
    console.warn(
      `[ensure-raknet] no prebuilt raknet binary for ${process.platform}-${process.arch}; ` +
        'a native build may be required (needs cmake + a C++ toolchain).'
    )
    process.exit(0)
  }
  fs.mkdirSync(path.dirname(target), { recursive: true })
  fs.copyFileSync(path.join(prebuilds, match, 'node-raknet.node'), target)
  console.log(`[ensure-raknet] staged prebuilds/${match}/node-raknet.node -> build/Release/`)
} catch (e) {
  console.warn('[ensure-raknet] skipped:', e.message)
}
