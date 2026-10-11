// The Warehouse — map definition for the map registry (src/world/map.js: format and API). One building, three halls in
// a row along +Z, joined by two rolling shutter doors. Flat concrete floor (h 0) everywhere. The walk field stops 1.6 m
// short of the side walls (the racks, crates and consoles that line them stand in that margin). The Mainframe Core is
// centred on the origin (the practice arena spawns its field round the origin).
//   dock    Loading Dock     z -182 … -112   56 m wide   open floor, containers and forklifts along the walls; the start
//   aisles  Server Aisles    z -108 …  -40   48 m wide   rows of server racks along the hall (carved set pieces)
//   core    Mainframe Core   z  -36 …   40   64 m wide   the arena: four pylons, the mainframe tower at the far end
// Gates: 'shutterA' (dock → aisles, z ≈ -110) and 'shutterB' (aisles → core, z ≈ -39), 18 m doorways.
const RACKS = [];                                                   // server rack rows in the aisles: 2 m × 12 m, x = ±13
for (const x of [-13, 13]) for (const z of [-98, -80, -62]) RACKS.push([x - 1, z, x + 1, z + 12]);
const PYLONS = [[-18, -16], [18, -16], [-18, 16], [18, 16]].map(([x, z]) => [x - 1, z - 1, x + 1, z + 1]);
const TOWER = [-5, 27, 5, 37];                                      // the mainframe
const DOCK_STACKS = [[-28, -176, -25.2, -163], [25.2, -160, 28, -147], [-28, -140, -25.2, -127], [25.2, -132, 28, -119]];   // containers on the walls

export default {
  id: 'warehouse',
  name: 'The Warehouse',
  zones: [
    { id: 'dock', name: 'Loading Dock', x: 0, z: -147, w: 56, d: 70 },
    { id: 'aisles', name: 'Server Aisles', x: 0, z: -74, w: 48, d: 68 },
    { id: 'core', name: 'Mainframe Core', x: 0, z: 2, w: 64, d: 76 },
  ],
  grid: [-64, -200, 64, 56],
  pieces: [
    { id: 'dock', rect: [-26.4, -180.6, 26.4, -112], h: 0 },
    { id: 'doorA', rect: [-9, -114, 9, -106], h: 0 },
    { id: 'aisles', rect: [-22.2, -108, 22.2, -40], h: 0 },
    { id: 'doorB', rect: [-9, -42, 9, -34], h: 0 },
    { id: 'core', rect: [-30.2, -36, 30.2, 38.6], h: 0 },
  ],
  carve: [...RACKS, ...PYLONS, TOWER, ...DOCK_STACKS],
  propCarve: [...RACKS, ...PYLONS, TOWER, ...DOCK_STACKS],
  route: [[0, -180], [0, -147], [0, -110], [0, -74], [0, -38], [0, 0], [0, 24]],
  gates: {
    shutterA: { rect: [-10, -112, 10, -108], open: true, name: 'Shutter A' },
    shutterB: { rect: [-10, -41, 10, -37], open: true, name: 'Shutter B' },
  },
  spawn: { story: { x: 0, z: -174, yaw: 0, tilt: -0.06 }, free: { x: 0, z: 0, yaw: 0, tilt: 0 } },
  freeAllies: { x: 0, z: -12, n: 16, cols: 4 },
  stage: 'dock',
  hq: [0, 30], hqName: 'CORE',
  // render data shared with the world builder (./world.js)
  racks: RACKS, pylons: PYLONS, tower: TOWER, stacks: DOCK_STACKS,
  /** Minimap: the rack rows, pylons and the mainframe as solid blocks, the painted centre lane. */
  minimap(g, X, Y, PPM) {
    g.fillStyle = 'rgba(70,255,138,0.10)';
    g.fillRect(X(1.5), Y(40), 3 * PPM, 222 * PPM);
    g.fillStyle = 'rgba(56,232,255,0.55)';
    for (const r of [...RACKS, ...PYLONS]) g.fillRect(X(r[2]), Y(r[3]), (r[2] - r[0]) * PPM, (r[3] - r[1]) * PPM);
    g.fillStyle = 'rgba(255,62,168,0.8)';
    g.fillRect(X(TOWER[2]), Y(TOWER[3]), (TOWER[2] - TOWER[0]) * PPM, (TOWER[3] - TOWER[1]) * PPM);
    g.fillStyle = 'rgba(200,210,220,0.4)';
    for (const r of DOCK_STACKS) g.fillRect(X(r[2]), Y(r[3]), (r[2] - r[0]) * PPM, (r[3] - r[1]) * PPM);
  },
};
