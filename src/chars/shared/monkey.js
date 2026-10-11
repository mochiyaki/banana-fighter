// Monkey parts for the fighters (content helper, head grid of src/chars/shared/body.js): a furred skull with a bare face
// patch, a muzzle that sticks out a voxel with nostrils and a grin, round ears on the sides, big eyes — and the tail, a
// spring chain (src/chars/shared/chains.js) off the back of the hips that curls up behind and swings with the moves.
// monkeyHead(c, o) → head boxes (c: { fur, furH, skin, skinD, eye, nostril, mouth }; o.ear: [y0, y1] ear height,
// o.speckle: fur highlight density 0-1). Hats, headphones and hair tufts go on top: head boxes authored later win.
import { vox } from '../../hero/model.js';
import { hash01 } from '../../core/rng.js';
import { B, Pt, both } from './body.js';

export function furOf(c, speckle = 0.25) { return (x, y, z) => (hash01(x, y, z) < speckle ? c.furH : c.fur); }

export function monkeyHead(c, { ear = [3, 8], speckle = 0.25 } = {}) {
  const fur = furOf(c, speckle), [e0, e1] = ear;
  const round = (y0, y1, z0, z1) => (x, y, z) => ((y === y0 || y === y1 - 1) && (z === z0 || z === z1 - 1) ? null : fur(x, y, z));
  return [
    B([-3, 1, -3], [4, 10, 3], fur),                                  // skull
    B([-3, 0, 2], [4, 8, 4], fur),                                    // face (front layer z 3)
    // the bare face patch: a heart — wide round the eyes, narrowing to the chin, the brow ridge left furred
    Pt([-2, 1, 3], [3, 7, 4], (x, y) => ((y === 1 && Math.abs(x - 0.5) > 1) || (y === 6 && x === 0) ? null : c.skin)),
    ...both(Pt([-3, 3, 3], [-2, 6, 4], c.skin)),                      // out to the cheeks
    // muzzle: one voxel proud of the face, lighter on top; nostrils, a wide grin with its corners up
    B([-2, 1, 4], [3, 4, 5], (x, y) => (y === 3 ? c.skin : c.skinD)),
    ...both(Pt([-1, 3, 4], [0, 4, 5], c.nostril)),
    Pt([-1, 1, 4], [2, 2, 5], c.mouth), ...both(Pt([-2, 2, 4], [-1, 3, 5], c.mouth)),
    // eyes: dark, a white catch-light above, furred brow ridge proud over them
    ...both(Pt([-2, 5, 3], [-1, 7, 4], c.eye)), ...both(Pt([-2, 6, 3], [-1, 7, 4], 0xffffff)),
    ...both(B([-3, 7, 4], [0, 8, 5], c.furH)),
    // ears: round discs out from the sides, the bowl painted skin
    ...both(B([-6, e0, -2], [-3, e1, 1], round(e0, e1, -2, 1))),
    ...both(Pt([-6, e0 + 1, -1], [-5, e1 - 1, 0], c.skinD)),
  ];
}

/** Tail segments for a chain: a furred rope, thick at the root, a lighter tuft at the tip (local −Y along the chain). */
export const tailSeg = (c) => (i, n) => {
  const w = i < 2 || i === n - 1 ? 2 : 1, tip = i === n - 1;
  return vox([B([-w, -4, -w], [w, 0, w], (x, y, z) => (tip ? (hash01(x, y, z) < 0.4 ? c.fur : c.furH) : furOf(c, 0.2)(x, y, z)))], 0.02, { jitter: 0.04, ao: 0.2 });
};

/** Add the tail to a fighter's chains: off the back of the hips, resting up and back in a curl, swinging with the body. */
export function addTail(chains, rig, c, { anchor = [0, -0.07, -0.1], n = 8, len = 0.075 } = {}) {
  return chains.add(rig.joints.hips, { anchor, rest: [0, 0.7, -1], n, len, stiff: 0.3, drag: 0.08, wind: 0.8, cone: 50, sway: 0.4, seg: tailSeg(c),
    hit: ['hips', ['thighL', 0.02], ['thighR', 0.02]] });
}
