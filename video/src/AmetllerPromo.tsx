import {AbsoluteFill, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import '@fontsource/inter/latin-800.css';
import '@fontsource/inter/latin-500.css';
import '@fontsource/ibm-plex-mono/latin-400.css';

const colors = {
  cream: '#F7F3E9',
  olive: '#5E5944',
  terminal: '#343A27',
  terminalHeader: '#4A5039',
  ivory: '#FAF7EC',
  muted: '#CBCAB5',
};
const mono = '"IBM Plex Mono", monospace';
const sans = 'Inter, sans-serif';
const repository = 'github.com/andreu-alegre/ametller-cli';

// Catálogo público consultado el 12/10/2026; no se consultó una cuenta.
const searchLines = [
  '[16490] Tomate mediterráneo — 0.90 € (5.00 €/kg)',
  '[53954] Tomate seco — 2.98 € (11.92 €/kg)',
  '[46077] Tomate Morado — 1.25 € (5.00 €/kg)',
  '57 resultados; mostrando 3 desde 0.',
];
// Datos ficticios explícitos; ningún ID, estado o ventaja de una cuenta real.
const couponLines = [
  '[demo-01] Cupón de ejemplo — estado: active',
  '[demo-02] Otro cupón de ejemplo — estado: active',
  '2 cupones mostrados de 2 en la cuenta móvil.',
];

const clamp = (frame: number, from: number, to: number) =>
  interpolate(frame, [from, to], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});

const BrandLogo = ({size}: {size: number}) => (
  <div style={{width: size, height: size, borderRadius: '50%', overflow: 'hidden', flexShrink: 0}}>
    <Img
      src={staticFile('ametller-logo.png')}
      alt="Ametller Origen"
      style={{width: size * 1.085, height: size * 1.085, margin: -size * 0.0425}}
    />
  </div>
);

const TerminalContent = ({frame, second}: {frame: number; second: boolean}) => {
  const start = second ? 172 : 30;
  const end = second ? 225 : 76;
  const resultsAt = second ? 234 : 88;
  const command = second ? 'ametller coupons --status active' : 'ametller search tomate --limit 3';
  const lines = second ? couponLines : searchLines;
  const typed = command.slice(0, Math.floor(clamp(frame, start, end) * command.length));
  const outputReady = frame >= resultsAt;
  const blink = Math.floor(frame / 12) % 2 === 0;
  const opacity = second ? clamp(frame, 170, 180) : 1 - clamp(frame, 156, 170);
  return (
    <div style={{opacity, fontFamily: mono, color: colors.ivory}}>
      <div style={{fontSize: 48, lineHeight: '72px', whiteSpace: 'pre'}}>
        <span style={{color: colors.muted}}>$ </span>{typed}
        {!outputReady ? <span style={{opacity: blink ? 1 : 0}}>▍</span> : null}
      </div>
      <div style={{paddingTop: 24}}>
        {lines.map((line, index) => {
          const reveal = clamp(frame, resultsAt + index * 6, resultsAt + index * 6 + 8);
          return (
            <div key={line} style={{
              fontSize: index === lines.length - 1 ? 30 : 38,
              color: index === lines.length - 1 ? colors.muted : colors.ivory,
              lineHeight: '58px',
              whiteSpace: 'pre',
              opacity: reveal,
              transform: `translateY(${(1 - reveal) * 8}px)`,
            }}>{line}</div>
          );
        })}
        <div style={{opacity: frame > resultsAt + lines.length * 6 + 10 && blink ? 1 : 0, fontSize: 40, lineHeight: '64px', color: colors.muted}}>$ ▍</div>
      </div>
    </div>
  );
};

export const AmetllerPromo = () => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const entrance = spring({frame, fps, config: {damping: 24, stiffness: 95, mass: 0.85}});
  const terminalEntrance = spring({frame: frame - 8, fps, config: {damping: 24, stiffness: 95}});
  const outro = clamp(frame, 292, 316);
  const sceneOpacity = 1 - outro;
  return (
    <AbsoluteFill style={{backgroundColor: colors.cream, overflow: 'hidden', fontFamily: sans, color: colors.olive}}>
      <AbsoluteFill style={{
        opacity: 0.25,
        backgroundImage: 'radial-gradient(ellipse at 50% 58%, #DDD6C4 0%, transparent 70%)',
      }} />

      <div style={{
        position: 'absolute', left: 172, top: 96, display: 'flex', alignItems: 'center', gap: 42,
        opacity: entrance * sceneOpacity,
        transform: `translateY(${(1 - entrance) * 18}px)`,
      }}>
        <BrandLogo size={158} />
        <div style={{fontSize: 96, fontWeight: 800, letterSpacing: -5}}>ametller-cli</div>
      </div>

      <div style={{
        position: 'absolute', left: 160, top: 320, width: 1600, height: 594,
        borderRadius: 32, overflow: 'hidden',
        backgroundColor: colors.terminal,
        border: '2px solid #76795B',
        boxShadow: '0 30px 65px #403D3024, 0 4px 10px #403D300C',
        opacity: terminalEntrance * sceneOpacity,
        transform: `translateY(${(1 - terminalEntrance) * 38 + outro * 18}px) scale(${0.975 + terminalEntrance * 0.025 - outro * 0.025})`,
      }}>
        <div style={{height: 76, backgroundColor: colors.terminalHeader, display: 'flex', alignItems: 'center', padding: '0 38px', gap: 17}}>
          {['#A4A16D', '#C5C5A9', '#777B55'].map((color) => <div key={color} style={{width: 22, height: 22, borderRadius: '50%', backgroundColor: color}} />)}
          <div style={{marginLeft: 'auto', color: colors.muted, fontSize: 23, fontFamily: mono}}>ametller-cli</div>
        </div>
        <div style={{padding: '42px 68px'}}>
          <TerminalContent frame={frame} second={frame >= 170} />
        </div>
      </div>

      <div style={{
        position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column',
        opacity: outro, transform: `translateY(${(1 - outro) * 20}px)`,
      }}>
        <BrandLogo size={134} />
        <div style={{fontSize: 112, fontWeight: 800, letterSpacing: -5, marginTop: 34}}>ametller-cli</div>
        <div style={{fontFamily: mono, fontSize: 36, marginTop: 30, letterSpacing: -0.5}}>{repository}</div>
      </div>

      <div style={{position: 'absolute', bottom: 56, width: '100%', textAlign: 'center', fontFamily: mono, fontSize: 28, letterSpacing: 0.2, opacity: entrance}}>
        CLI no oficial · Demo ilustrativa
      </div>
    </AbsoluteFill>
  );
};
