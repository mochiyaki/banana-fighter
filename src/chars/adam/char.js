// Adam — character entry (contract: src/chars/index.js).
import { ADAM_KIT } from './kit.js';

// 20×20 portrait: a brown monkey — fur crest, round ears out past the headphones, a bare face, a grin, black tee
const FACE = [
  '....................',
  '......FFFFFFFF......',
  '.....FFFfFFFFFF.....',
  '....FFFFFFFfFFFF....',
  '...PPFFfFFFFFFFPP...',
  '...PFFFFFfFFFFfFP...',
  '..PPFFFFFFFFFFFFPP..',
  '..PCFFFSSSSSSFFFCP..',
  '..PCFSSSSSSSSSSFCP..',
  '..PCSSwESSSSEwSSCP..',
  '..PPSSEESSSSEESSPP..',
  '.FFPSSSSSSSSSSSSPFF.',
  'FFfFSSSNSSSSNSSSFfFF',
  'FFFFsSSSSSSSSSSsFFFF',
  '.FFFsSMSSSSSSMSsFFF.',
  '..F..sSMMMMMMSs..F..',
  '......ssSSSSss......',
  '...TTTTtFFFFTTTT....',
  '.TTTTTTTTttTTTTTTT..',
  'TTtTTTCTCTCTCTTTTtT.',
];
const PAL = { F: '#5a3a22', f: '#7a5230', P: '#1a1c22', C: '#38e8ff', S: '#e8b88e', s: '#c9966e', N: '#6a3a2a', E: '#1a1214', w: '#ffffff',
  M: '#5a2a24', T: '#17171b', t: '#0d0d10' };

export const ADAM = {
  id: 'adam',
  name: 'Adam', role: 'The Broadcaster', tag: 'ADAM',
  motto: 'Loud, fast and always on air',
  weapon: 'Microphone & Drone',
  bio: ['A monkey who learned to hack by jamming the school PA system. Black T-shirt, jeans, headphones he never takes off.',
    'His mic stand sweeps a whole rank at once, his screams rattle them from five metres — and his drone does the rest.'],
  stats: { atk: 4, def: 3, speed: 3, range: 5 }, musou: { name: 'Sonic Boom', desc: 'Three screams, a drone strafe, then the mic drop.' }, accent: '#38e8ff',
  lines: {
    intro: 'Mic check. One, two — you\'re all getting dropped.',
    musouEnd: 'And that\'s the show. Thank you, warehouse!',
    copy: ['Turn it up', 'Drop the bass'],
  },
  portrait: { face: FACE, pal: PAL },
  kit: ADAM_KIT,
};
