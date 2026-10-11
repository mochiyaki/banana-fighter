// Ana — character entry (contract: src/chars/index.js).
import { ANA_KIT } from './kit.js';

// 20×20 portrait: a golden monkey — sailor hat with a navy band, fur twin tails with red ribbons, round ears, big teal eyes
const FACE = [
  '......WWWWWWWW......',
  '.....WWWWWWWWWW.....',
  '....NNNNNNNNNNNN....',
  '...FFFFFfFFFFfFFF...',
  '..RFFFfFFFFFFFFFFR..',
  '.RRFFFFFFfFFFFfFFRR.',
  '.FFFFFSSSSSSSSFFFFF.',
  '.FFFFSSSSSSSSSSFFFF.',
  'FfFFSEESSSSSSEESFFfF',
  'FFFFSEwSSSSSSEwSFFFF',
  'FFFFSIISSSSSSIISFFFF',
  '.FF.SSSSNSSNSSSS.FF.',
  '.Ff.SPSSSSSSSSPS.fF.',
  '.FF.sSSSMMMMSSSs.FF.',
  '.fF..sSSSSSSSSs..Ff.',
  '..F...ssSSSSss...F..',
  '...NNNNNFFFFNNNNN...',
  '.NNwwNNNNTTNNNNwwNN.',
  'NNNNNNNNTTTTNNNNNNNN',
  'WWWWWWWWWTTWWWWWWWWW',
];
const PAL = { W: '#f4f4f0', N: '#1f3a6e', w: '#ffffff', F: '#b07a3e', f: '#cf9a56', R: '#d0402a', S: '#f6d2b4', s: '#d6a88a', E: '#1a1214', I: '#2a9a8a',
  P: '#f2a8a0', M: '#c0646a', T: '#d0402a' };

export const ANA = {
  id: 'ana',
  name: 'Ana', role: 'The Influencer', tag: 'ANA',
  motto: 'Every hit goes viral',
  weapon: 'Cellphone & Laptop',
  bio: ['Top of her class, top of the feed. A golden monkey in a white sailor dress, twin tails and two devices that never leave her hands.',
    'The fastest hands in the bracket: phone in the right, laptop in the left, a new hit every third of a second.'],
  stats: { atk: 3, def: 2, speed: 5, range: 3 }, musou: { name: 'Viral Storm', desc: 'Six dash cuts, a spinning storm, then the burst.' }, accent: '#ff7eb6',
  lines: {
    intro: 'Smile! You\'re about to trend for all the wrong reasons.',
    musouEnd: 'Posted. Shared. Deleted. Next!',
    copy: ['Like and share', 'Going viral'],
  },
  portrait: { face: FACE, pal: PAL },
  kit: ANA_KIT,
};
