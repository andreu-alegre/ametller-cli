import {Composition} from 'remotion';
import {AmetllerPromo} from './AmetllerPromo';

export const Root = () => (
  <Composition
    id="AmetllerPromo"
    component={AmetllerPromo}
    width={1920}
    height={1080}
    fps={30}
    durationInFrames={360}
  />
);
