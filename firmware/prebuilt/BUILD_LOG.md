# Bundled firmware build log

`tools/make_prebuilt.py` adds an entry here (newest first) every time it refreshes `firmware/prebuilt/`.
The git history keeps the binaries of the **last 3 builds** only (see PUBLISHING.md); older builds are listed
here so they stay identifiable by version, time and SHA-256.

## 0.2.2-wip — built 2026-11-14 11:09

What changed: Fix: left/right was mirrored for both radars; new frozen-target filter (default 10 s)

Source hash: `691a1784c28451a8072757a16f56696783e541540e18f28e618706379c30ac6b`

| Build | File | Bytes | SHA-256 |
|---|---|---|---|
| `c3-supermini` | blip-c3-supermini-full.bin | 1333696 | `182006e257f281b687ec947edde8ece352b695ac40c333edcabb9474cf2ab302` |
| `s3-pico` | blip-s3-pico-full.bin | 1209584 | `608b71ca72c3590cfa6826ca92dc8311a69a39f25ac345eb070227a49c85a5f7` |
| `c3-supermini-ld2450` | blip-c3-supermini-ld2450-full.bin | 1333664 | `10ed7be1a453fcf962450e203f6dcbc4b135c570673e763bc9a72882442778f5` |
| `s3-pico-ld2450` | blip-s3-pico-ld2450-full.bin | 1209552 | `2fe13a4d869306c9abd0fede916883f34f84a566649a3d7ab5cda52950c2826f` |
| `c3-supermini-bench` | blip-c3-supermini-bench-full.bin | 1261728 | `36f05f72ff164d9d355d1e2f215e89e9fb7cf5327255f8c981947fce6b7b200d` |
| `s3-pico-bench` | blip-s3-pico-bench-full.bin | 1144240 | `74d5c1bc3fd9984f02ae5300ea1592bc05b230ea7f93f2680d3e379c9e765b4a` |

## 0.2.2-wip — built 2026-11-13 21:12

What changed: Metre rings on the scope; two-line target labels

Source hash: `6bbfaa353905ea3dbfb1fec7be94557251a256c92af3f08463b1849c96e9f09d`

| Build | File | Bytes | SHA-256 |
|---|---|---|---|
| `c3-supermini` | blip-c3-supermini-full.bin | 1332688 | `3af5686dca9ccdd75af86752b70b67ed0101b41726fa9f7518464256a62f4c79` |
| `s3-pico` | blip-s3-pico-full.bin | 1208768 | `cea46d304aabb8a67a01ff4ef83364592dd3b0cca611b2989ab7a11b5576c6be` |
| `c3-supermini-ld2450` | blip-c3-supermini-ld2450-full.bin | 1332656 | `609d198b26c6d9c3a88eec6decad37e5ee540c62c06507eed40eaa1a4909ae68` |
| `s3-pico-ld2450` | blip-s3-pico-ld2450-full.bin | 1208736 | `8b651d4a33cf12bce0655713f81791696c1b763d3d4f762b0e75bfe66442a771` |
| `c3-supermini-bench` | blip-c3-supermini-bench-full.bin | 1261728 | `36f05f72ff164d9d355d1e2f215e89e9fb7cf5327255f8c981947fce6b7b200d` |
| `s3-pico-bench` | blip-s3-pico-bench-full.bin | 1144240 | `74d5c1bc3fd9984f02ae5300ea1592bc05b230ea7f93f2680d3e379c9e765b4a` |

## 0.2.2-wip — built 2026-11-13 21:10

What changed: Scope labels: distance first, then closer/away speed, track number marked # (was read as a distance)

Source hash: `f19cc7d46c0fea6709753128c1238f91d7ead62fa566000f0b9333b932c367ef`

| Build | File | Bytes | SHA-256 |
|---|---|---|---|
| `c3-supermini` | blip-c3-supermini-full.bin | 1332528 | `079cb83e0fe11b9d955d425bfbc240a3dba397f9b9d50c6ba97697bcee5cbcf9` |
| `s3-pico` | blip-s3-pico-full.bin | 1208608 | `d275292b0e9c1ee65031f5560ef156f3f2cf8eb94327871a2d5a8aeb6cf4ace3` |
| `c3-supermini-ld2450` | blip-c3-supermini-ld2450-full.bin | 1332496 | `f6dbaad68fad52d04992b60269056bf01ecd8da27c0174fc831ecc791f158997` |
| `s3-pico-ld2450` | blip-s3-pico-ld2450-full.bin | 1208576 | `2fc12df9d7cda516f32b8c37b7c6dd08d53d6fed5ae1c0d4377205a3f536936b` |
| `c3-supermini-bench` | blip-c3-supermini-bench-full.bin | 1261728 | `36f05f72ff164d9d355d1e2f215e89e9fb7cf5327255f8c981947fce6b7b200d` |
| `s3-pico-bench` | blip-s3-pico-bench-full.bin | 1144240 | `74d5c1bc3fd9984f02ae5300ea1592bc05b230ea7f93f2680d3e379c9e765b4a` |

## 0.2.2-wip — built 2026-11-13 20:53

What changed: 2 MB flash layout for all boards (S3 build was 16 MB and boot-looped on 4 MB S3 boards); S3 log also on native USB

Source hash: `a6259a769297dc502051e2670c6c87ae524b7a356827a141f90484c642ef1a04`

| Build | File | Bytes | SHA-256 |
|---|---|---|---|
| `c3-supermini` | blip-c3-supermini-full.bin | 1332336 | `3c258beb85862a40250eac78adf723e4ab2ef7315f9f3f51e02ca762b69bf171` |
| `s3-pico` | blip-s3-pico-full.bin | 1208416 | `0b577e710fbbc1d8478e0f97176113803e2df773aedfee0559a564baee3055ec` |
| `c3-supermini-ld2450` | blip-c3-supermini-ld2450-full.bin | 1332304 | `90478568d50a4dfd5f2d80fa86daafba763ffccd241dc626d752584bbb75a3dc` |
| `s3-pico-ld2450` | blip-s3-pico-ld2450-full.bin | 1208384 | `0f3382c8651d51e551149b7a48756f2252ce51e278e9ea5c3e65a5f6b470a367` |
| `c3-supermini-bench` | blip-c3-supermini-bench-full.bin | 1261728 | `36f05f72ff164d9d355d1e2f215e89e9fb7cf5327255f8c981947fce6b7b200d` |
| `s3-pico-bench` | blip-s3-pico-bench-full.bin | 1144240 | `74d5c1bc3fd9984f02ae5300ea1592bc05b230ea7f93f2680d3e379c9e765b4a` |

## 0.2.2-wip — built 2026-11-13 14:34

What changed: Clutter options: minimum range, edge limit, handheld mode, strict ghost test; Show filtered covers them

Source hash: `9626a8a0c65aefa5d31529530db2326fb9e1a184f688cd6d3ab359606ed275b8`

| Build | File | Bytes | SHA-256 |
|---|---|---|---|
| `c3-supermini` | blip-c3-supermini-full.bin | 1332336 | `5ce8c6f2d61a1bb9cc28c4ef98ae5f12a43cbac1b9bf8655e90045e61cfd5d50` |
| `s3-pico` | blip-s3-pico-full.bin | 1203088 | `88f8380604594f376ca62edbb20bbdca20b4e1c9d42dcdaefbe87eb8f3f79df0` |
| `c3-supermini-ld2450` | blip-c3-supermini-ld2450-full.bin | 1332304 | `3c493d286fa150a216afd33c2145f2f777a61c7c52ea4c5434be9f88ede93e0a` |
| `s3-pico-ld2450` | blip-s3-pico-ld2450-full.bin | 1203056 | `fc84263b05936de1cd5bbf8893754b93e0e534a7f105ceb5691542b221aa8d1d` |
| `c3-supermini-bench` | blip-c3-supermini-bench-full.bin | 1261728 | `58cb57953e5f4c3d27f99c909b451dac9dd38c9c24090fe1e74be00ef560aae7` |
| `s3-pico-bench` | blip-s3-pico-bench-full.bin | 1120288 | `347562fb60936e78fd50856872662ce7bf8528fe1c4c615abb49c5c6d1084c81` |

## 0.2.2-wip — built 2026-11-13 00:26

What changed: OLED auto-scan at boot (0x3C/0x3D); Track 1/3 switch on the Radar page

Source hash: `e11b93433eb161d475a1a17ef35ef9864b841ff17ab9ab07d157185c9c6642f3`

| Build | File | Bytes | SHA-256 |
|---|---|---|---|
| `c3-supermini` | blip-c3-supermini-full.bin | 1328032 | `982470a897c183108338f47ec2ca112128639cac62490b8731ee21cd6f7df014` |
| `s3-pico` | blip-s3-pico-full.bin | 1199472 | `e9c527dab36e385c4ed30d8e0e170532cde14a8e31b38ee8660d775d53bdaf49` |
| `c3-supermini-ld2450` | blip-c3-supermini-ld2450-full.bin | 1328000 | `04916a5e5f446a1ab2419600a704a11c81d6d4fc2334b40d30bbeb28201d2d22` |
| `s3-pico-ld2450` | blip-s3-pico-ld2450-full.bin | 1199440 | `fc146bab42309e831ecc79a4ab6859d230e2d028a93aac7c66403bfd5618d74d` |
| `c3-supermini-bench` | blip-c3-supermini-bench-full.bin | 1261728 | `33d0d67f5c065f7d7d106b92cf3e33ab8f7a329f5e37747906bb64987c7ed425` |
| `s3-pico-bench` | blip-s3-pico-bench-full.bin | 1120288 | `94f91821ecb23f53b240e2b4d140a5273459b8112bb47aab86832d6593c50096` |

## 0.2.2-wip — built 2026-11-08 15:32

What changed: Stetho: shallow duck + limiter + freeze/excursion hold (post-bump dropout), burst blanker, ADC averaging option; page-side heart/breath pattern recognition

Source hash: `efc95b49de5ab10dd85b308735857d5bf8779bbd16745b47c287bd7a58770618`

| Build | File | Bytes | SHA-256 |
|---|---|---|---|
| `c3-supermini` | blip-c3-supermini-full.bin | 1327696 | `1bdef0c41e5bae0843911b6e7a653ec79bce186b2b982e36cbeb597d9838aaa3` |
| `s3-pico` | blip-s3-pico-full.bin | 1199120 | `8fc44c61e1830a717435b7194c74558313a08451f2bb2e64632e42c9bd648d07` |
| `c3-supermini-ld2450` | blip-c3-supermini-ld2450-full.bin | 1327664 | `927417a1c6aa186ff3ebd042686c80a629729a8c11bf4aeb45e9a302a8def4bf` |
| `s3-pico-ld2450` | blip-s3-pico-ld2450-full.bin | 1199088 | `9f8ea750433c44c5981811d0f133341a9898a667642a472d8cc4c9c92ab3aeeb` |
| `c3-supermini-bench` | blip-c3-supermini-bench-full.bin | 1261728 | `33d0d67f5c065f7d7d106b92cf3e33ab8f7a329f5e37747906bb64987c7ed425` |
| `s3-pico-bench` | blip-s3-pico-bench-full.bin | 1120288 | `94f91821ecb23f53b240e2b4d140a5273459b8112bb47aab86832d6593c50096` |

## 0.2.2-wip — built 2026-11-08 13:46

What changed: Stability test lab: runtime /api/lab switches, synthetic audio source, bump-gate latch cap, status JSON clamp

Source hash: `cde45df6d081a660d30c58757a5d7927ba0337893a3bc7e2104368654b737fe5`

| Build | File | Bytes | SHA-256 |
|---|---|---|---|
| `c3-supermini` | blip-c3-supermini-full.bin | 1320080 | `3c84d09251d0e29f847c0138eddaaa64ae37d9dd0f8d77a8a6171a6b835bafaa` |
| `s3-pico` | blip-s3-pico-full.bin | 1191920 | `142f50fb06fafbbfe0dab6792b6b0c0b530f7658f577d146ca0219aa6cec1bbf` |
| `c3-supermini-ld2450` | blip-c3-supermini-ld2450-full.bin | 1320032 | `59c6e6ccadf83de405cd05898fdf9470a6b5bcd2746e0ac93f4aa8713c79d5f6` |
| `s3-pico-ld2450` | blip-s3-pico-ld2450-full.bin | 1191872 | `7fe456e4c3ed7f3fe042486650121e24a87564d600e108e1dfd8b4a04f31fe0e` |
| `c3-supermini-bench` | blip-c3-supermini-bench-full.bin | 1258928 | `6bc44598f76ea1c1207a15f65e8f49b56a836259df571518dafc403028444307` |
| `s3-pico-bench` | blip-s3-pico-bench-full.bin | 1117888 | `c0179ebe6314c114a2ad6dce49dca870a2ae5ab4c887fb4c97e68461b0244be2` |

## 0.2.2-wip — built 2026-11-08 12:16

What changed: Fix: Stetho opened the ADC in one task and closed it in another, which asserts on every stop; the audio task now owns both. Bench stage 2 now streams audio to an open page.

Source hash: `a43b0daa047cfb0a8f01930bd11e0728fa8ea0b41d9cdf88ae16c5c831244785`

| Build | File | Bytes | SHA-256 |
|---|---|---|---|
| `c3-supermini` | blip-c3-supermini-full.bin | 1317216 | `38cda01f74cdfdb1ae6ae8da6225538e733c5c74b53f492608ebabf9d9cd904e` |
| `s3-pico` | blip-s3-pico-full.bin | 1188832 | `f3bd5dcc9f801a40ef54e82831eb5d87dcce5ffb2069dcf3c695470fa829b9fa` |
| `c3-supermini-ld2450` | blip-c3-supermini-ld2450-full.bin | 1317200 | `39833dd6762f8d32eb3a2301f3684f17fb0ddf2ffa1e1012e5e82339d3825b8a` |
| `s3-pico-ld2450` | blip-s3-pico-ld2450-full.bin | 1188832 | `3aa9802e0f80346a494c61098e63dd0d033a4eb7280ea5e83a0823d82e57b405` |
| `c3-supermini-bench` | blip-c3-supermini-bench-full.bin | 1261008 | `e1ea28c0b8df1b9430507440a2337457b9cab8247bd3fffeea2d673206b3fe52` |
| `s3-pico-bench` | blip-s3-pico-bench-full.bin | 1119568 | `8f2f8201dc7f75437bcb16b51f8ec6d5acb0b7eb9368e6133a3a86c6042cbb64` |

## 0.2.2-wip — built 2026-11-08 02:28

What changed: A/B test: old guarded Stetho send restored (availableForWriteAll, newest 2, flush 6), WS queue back to the library default 32; bench test added to the bundle

Source hash: `b9d9aa2d8c40da7be7098eef56ff68d5bdf656c951710a4255a3a4ff24f78469`

| Build | File | Bytes | SHA-256 |
|---|---|---|---|
| `c3-supermini` | blip-c3-supermini-full.bin | 1317040 | `b88aca4ec986c6d4e3455d2dc65cf83ccc983eefaeef9cb4396eaeca7b03a79e` |
| `s3-pico` | blip-s3-pico-full.bin | 1188672 | `30c7e5f9d57be15121cba70082e0fe067c3b65f466f508d600adaa92f1c25e96` |
| `c3-supermini-ld2450` | blip-c3-supermini-ld2450-full.bin | 1317024 | `eab661f180de0de8c140a278ae816f84c04ce4b6c414fe4bb0b5da4c0e06b9e4` |
| `s3-pico-ld2450` | blip-s3-pico-ld2450-full.bin | 1188656 | `cdea811ff04f8afd232cb7889eadda7aee436953923795d49819dc19ec66470f` |
| `c3-supermini-bench` | blip-c3-supermini-bench-full.bin | 1259472 | `19316845ffb785fdd2f31def99375255d25ddaa05140db4120939c2707e3e55f` |
| `s3-pico-bench` | blip-s3-pico-bench-full.bin | 1118080 | `ef609869dbc6dd9176bd5480cdda9eece194e0f2d609aa9553a9473da2b8feee` |

## 0.2.2-wip — built 2026-11-08 01:05

What changed: The drain-cap fix from the previous build did not stop the crash — a fresh log showed it still happens with no Wi-Fi disconnect anywhere nearby, which rules that theory out. Added: the failed-allocation hook never actually fired in that log, ruling out heap exhaustion too. Sped up the health line to every 1 s while Stetho is running (was 10 s — too slow to catch anything before a 4-9 s crash), and added an immediate log line the instant any single loop() pass takes over 150 ms, so the next crash log should finally show whether this is a CPU-time stall or a true wait.

Source hash: `7b5406f13be459202b300fcc9ccaebd76790260e1305fb5365ee6cc610a208d2`

| Build | File | Bytes | SHA-256 |
|---|---|---|---|
| `c3-supermini` | blip-c3-supermini-full.bin | 1316496 | `b22c46f672e62404faf5923a2053d38a4efad85e435fafadf37c34bb44d7e23f` |
| `s3-pico` | blip-s3-pico-full.bin | 1188208 | `5c0e9d32c5f05d10290c03dc7aabfaf534af04ff5dcdfde99474540160a942e0` |
| `c3-supermini-ld2450` | blip-c3-supermini-ld2450-full.bin | 1316496 | `ed03480372fd46382658d8da4b2885f63b4fb218a2689803b7007bb447e89818` |
| `s3-pico-ld2450` | blip-s3-pico-ld2450-full.bin | 1188192 | `750aaab305de996afa63687dc37814bf3ea72c3ff6fe23a53df9ae82b6ccb1d6` |

## 0.2.2-wip — built 2026-11-07 20:57

What changed: Diagnosed the C3 crash: loopTask and async_tcp both touch AsyncWebSocket's internal lock; Stetho's drain loop could burst many binaryAll() calls at once right as a client dropped. Capped the drain to 4 packets/tick, and added a failed-allocation hook plus async_tcp's own task state/stack headroom to the health line so the next crash log shows exactly what it was doing and what allocation (if any) failed.

Source hash: `1e27c3529f32d26d66a029c9e413dd91580c74522faa487e5eabd444a4496978`

| Build | File | Bytes | SHA-256 |
|---|---|---|---|
| `c3-supermini` | blip-c3-supermini-full.bin | 1316352 | `0518b81bfef62e6dec916b9f260d9b2c67aeb729b20f14735d85aeb8df211c2e` |
| `s3-pico` | blip-s3-pico-full.bin | 1188064 | `a79e92d22dcdfe33afbbecb82f90fd4145074e158897570f853056260b8f7d2e` |
| `c3-supermini-ld2450` | blip-c3-supermini-ld2450-full.bin | 1316352 | `34544f2a37bb86ca22a9fe781cedf76c996e70254dd90b717a8ac42fe0e52027` |
| `s3-pico-ld2450` | blip-s3-pico-ld2450-full.bin | 1188048 | `49d1a449d89f178edc901256554fc2b06cf82679a006c9229853e12e4a6bdd5b` |

## 0.2.2-wip — built 2026-11-07 17:11

What changed: Node log (crash-surviving, /api/log, health line every 10 s, Wi-Fi join/leave with reasons), Wi-Fi power setting (C3 default 8.5 dBm), build time on the page

Source hash: `d0e1a2471f3680619da458b037029a34b051528c1f8e97f38b9b1ab78b0942eb`

| Build | File | Bytes | SHA-256 |
|---|---|---|---|
| `c3-supermini` | blip-c3-supermini-full.bin | 1315520 | `10364f35dc559dec2f5cda86a54fc66177184b5d9e38e5d08577df8b10d372c2` |
| `s3-pico` | blip-s3-pico-full.bin | 1187264 | `0ecabfd9c5d1a7c9e5a44cb3edcab82796b0713548179730cab5a16f267cd7f9` |
| `c3-supermini-ld2450` | blip-c3-supermini-ld2450-full.bin | 1315488 | `2c182c0f44b24656a07b9f97eb63a749502ed6a492dc6deadaf3adf7c8587b4d` |
| `s3-pico-ld2450` | blip-s3-pico-ld2450-full.bin | 1187232 | `b4f814bc7f8c300e881c52e63a99409c0440c7005568c255b4e01832986f4413` |

## 0.2.2-wip — built 2026-11-07 16:46

What changed: Fix: node froze seconds after Stetho started. WebSocket sending moved back into loop() (the separate sender task froze a real C3); 'starting…' instead of a false 'could not start'

Source hash: `1e4f2f06335cb723c13355c8f8abbc6bc0b5fce8d2988cef454b5e33dcf06c6e`

| Build | File | Bytes | SHA-256 |
|---|---|---|---|
| `c3-supermini` | blip-c3-supermini-full.bin | 1310720 | `762b2b6479d4017f80235481c2d092c9992b1f4eec6455912dcb559b6838ff04` |
| `s3-pico` | blip-s3-pico-full.bin | 1183072 | `db8415b88581fdaedaf875049c398b512824167b9a53f20d0c63cf5aec4f9881` |
| `c3-supermini-ld2450` | blip-c3-supermini-ld2450-full.bin | 1310688 | `eb239fb208739f98a8fff0e892e0c6bec6f643896f33018aa61658aaa5a55b49` |
| `s3-pico-ld2450` | blip-s3-pico-ld2450-full.bin | 1183040 | `f0d4d67c5bf28de780a9f23cc78bcec702f6fe90814e142149f7bd3bccc87112` |

## 0.2.2-wip — built 2026-11-07 14:38

What changed: Stetho tab shows reset reason, start count and 'no update for N s'; serial prints the start reason

Source hash: `c069630136879144e17954b13624fb8acb79a7ab17d9f6a1240c1bfcebf19090`

| Build | File | Bytes | SHA-256 |
|---|---|---|---|
| `c3-supermini` | blip-c3-supermini-full.bin | 1311200 | `be1623898e7e1e2a551082ee4186e6c91c55df4fc4474c6c565a82d5c54505dd` |
| `s3-pico` | blip-s3-pico-full.bin | 1183456 | `8224295b652c7e55fb3da20f905c45175684fecaf919b8934abaa4b0b8e1eab6` |
| `c3-supermini-ld2450` | blip-c3-supermini-ld2450-full.bin | 1311168 | `0e7777345b52abdac7f6e9022341817686febbc42cc4d3b91328f20a4400afdf` |
| `s3-pico-ld2450` | blip-s3-pico-ld2450-full.bin | 1183424 | `9e013a60b6f4d8e13d5863a6bc4e47a2bba345ca15ae7c79b0a59ff4a363497a` |

## 0.2.2-wip — built 2026-11-07 14:24

What changed: Stetho: mu-law audio in 32 ms packets (a quarter of the messages), all WebSocket output from one task with status first

Source hash: `d342713a1cc282d167101bb576e2ee94c258d853193a8ed8c5b5d13bce9d4c06`

| Build | File | Bytes | SHA-256 |
|---|---|---|---|
| `c3-supermini` | blip-c3-supermini-full.bin | 1310432 | `1c513679dad9f79d8da1449bf7c7d83afa5503ac833c220d1c563003caa2f3a7` |
| `s3-pico` | blip-s3-pico-full.bin | 1182768 | `c3200949c506aa57a3e25925a28a1128edf161fe6869ebf291fbb4eb6030140d` |
| `c3-supermini-ld2450` | blip-c3-supermini-ld2450-full.bin | 1310400 | `eb32d362f8d1fea3620a73d2f6e449193d6207308e21b83bc4798dc8e13fd5b3` |
| `s3-pico-ld2450` | blip-s3-pico-ld2450-full.bin | 1182736 | `fff3d94f58653998b49af8d43291efb0e58428f292b47ba3bb81096bb095e62e` |

## 0.2.2-wip — built 2026-11-07 13:36

What changed: Stetho packets from their own task, WebSocket queue cap, OLED probe

Source hash: `a3716c2fb9d3f17a4f1c22b148b64621151533d9569392c1088517dfaf0ca5f5`

| Build | File | Bytes | SHA-256 |
|---|---|---|---|
| `c3-supermini` | blip-c3-supermini-full.bin | 1309808 | `aee5373f208e7c30e26514062f19b1fc2cc863e3c00bbfdfb680280e940e20c7` |
| `s3-pico` | blip-s3-pico-full.bin | 1182160 | `5aad0c014cca5e789bf3a3693f05a9c82c021e60b595821d0dd6fd232df2369e` |
| `c3-supermini-ld2450` | blip-c3-supermini-ld2450-full.bin | 1309776 | `484ec91dc91da60ad55468ab9f8e84b858b902336c4f060b9dac0dd868a10ed2` |
| `s3-pico-ld2450` | blip-s3-pico-ld2450-full.bin | 1182128 | `891d8d19a7fd1a1726c9d995dbbdb4f2ffa882b2854694144348f22b18f72f76` |

## 0.2.2-wip — built 2026-11-07 12:47

What changed: Stetho diagnostics on the Stetho tab (pin voltage, start errors)

Source hash: `319740020c43b09e02ee536405f5c877a3e97a61bf9e202c1117bc4adbd4329e`

| Build | File | Bytes | SHA-256 |
|---|---|---|---|
| `c3-supermini` | blip-c3-supermini-full.bin | 1309264 | `16023be402436d396ba9e61dac6b1d42902687a1c9e3c37c3b522efb41a4c0e4` |
| `s3-pico` | blip-s3-pico-full.bin | 1181600 | `b79a13deb3e70f2f586c6e7c06e7b5e7a3c315788749862515748150912ab60e` |
| `c3-supermini-ld2450` | blip-c3-supermini-ld2450-full.bin | 1309232 | `7e40c474e345f56d54ad4d70ea254e09f568b640e9def1ec5296f6c201f7e70a` |
| `s3-pico-ld2450` | blip-s3-pico-ld2450-full.bin | 1181568 | `b3b03082a119d81ab3da9e84d4d07d27ca0f7e0e7b2b73f57b82369d8d8bd24c` |

## 0.2.2-wip — built 2026-11-07 09:50

What changed: first bundled build: LD2450 option, unified Flash tab, Quick flash

Source hash: `94d5cdf12ace9a568fd95c7062216654e97943c2f70a4ea38a50a347f15c9291`

| Build | File | Bytes | SHA-256 |
|---|---|---|---|
| `c3-supermini` | blip-c3-supermini-full.bin | 1304160 | `5c4d9afce56d271d6f11f4e3dc38ee5fdd370892bfaf25a80faf18b75451ac04` |
| `s3-pico` | blip-s3-pico-full.bin | 1176448 | `1aca32afa2116126c3a3891256f4e0565ad993579a9f0550e46bb0aa422483c0` |
| `c3-supermini-ld2450` | blip-c3-supermini-ld2450-full.bin | 1304128 | `52d5a37a7177c39a9f9f95410c6d4b9feae71dd1fc87f1d7c29c9caa97d2f628` |
| `s3-pico-ld2450` | blip-s3-pico-ld2450-full.bin | 1176416 | `6d5d988366652b277e1665adda8cd6878cdcccd43390142341007a96ca10f544` |

