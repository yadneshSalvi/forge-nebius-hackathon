import { useMemo } from "react";
import { Canvas } from "@react-three/fiber";
import {
  BufferGeometry,
  Color,
  Float32BufferAttribute,
  Line,
  LineBasicMaterial,
  Quaternion,
  Vector3,
} from "three";
import type { Geometry, Sample, Vec3 } from "./types";
import { sampleAt } from "./data";

function colorOf(g: Geometry) {
  if (g.name.includes("protected")) return "#d69da4";
  if (g.name.includes("payload")) return "#89dce5";
  if (g.name.includes("tray") || g.name.includes("bay")) return "#878a9e";
  if (g.name.includes("finger")) return "#d5dce3";
  if (g.name.includes("gantry") || g.name.includes("carriage"))
    return "#c0cad4";
  if (g.rgba) return new Color(g.rgba[0], g.rgba[1], g.rgba[2]);
  return "#647582";
}
function RenderGeometry({
  geometry: g,
  sample,
  next,
  alpha,
  selected,
  onSelect,
}: {
  geometry: Geometry;
  sample?: Sample;
  next?: Sample;
  alpha: number;
  selected: string;
  onSelect: (name: string) => void;
}) {
  const current = sample?.bodies[g.body];
  const following = next?.bodies[g.body] || current;
  const position: Vec3 = current
    ? (current.position.map(
        (v, i) => v + ((following?.position[i] ?? v) - v) * alpha,
      ) as Vec3)
    : [0, 0, 0];
  const rotation = useMemo(() => {
    const q = current?.quaternion || [1, 0, 0, 0];
    const q2 = following?.quaternion || q;
    return new Quaternion(q[1], q[2], q[3], q[0]).slerp(
      new Quaternion(q2[1], q2[2], q2[3], q2[0]),
      alpha,
    );
  }, [current, following, alpha]);
  const localQ = g.quaternion;
  const isFloor = g.type === "plane" || /floor|table_top|ground/.test(g.name);
  const selectedBody = selected === g.body;
  const materialColor = selectedBody ? "#c4b5fd" : colorOf(g);
  return (
    <group position={position} quaternion={rotation}>
      <mesh
        position={g.position}
        quaternion={[localQ[1], localQ[2], localQ[3], localQ[0]]}
        castShadow={!isFloor}
        receiveShadow
        onClick={(event) => {
          event.stopPropagation();
          onSelect(g.body);
        }}
      >
        {g.type === "plane" ? (
          <planeGeometry
            args={[
              Math.max(g.size[0] * 2, 1.25),
              Math.max(g.size[1] * 2, 1.05),
            ]}
          />
        ) : g.type === "sphere" ? (
          <sphereGeometry args={[g.size[0], 20, 16]} />
        ) : g.type === "cylinder" ? (
          <cylinderGeometry args={[g.size[0], g.size[0], g.size[1] * 2, 24]} />
        ) : (
          <boxGeometry
            args={[
              Math.max(0.001, g.size[0] * 2),
              Math.max(0.001, g.size[1] * 2),
              Math.max(0.001, g.size[2] * 2),
            ]}
          />
        )}
        <meshStandardMaterial
          color={isFloor ? "#202b34" : materialColor}
          metalness={isFloor ? 0.1 : 0.4}
          roughness={isFloor ? 0.91 : 0.43}
          emissive={selectedBody ? "#4e3c7c" : "#000000"}
          emissiveIntensity={0.2}
        />
      </mesh>
    </group>
  );
}
function Trajectory({ samples, body }: { samples: Sample[]; body: string }) {
  const line = useMemo(() => {
    const points = samples
      .filter((_, i) => i % Math.max(1, Math.floor(samples.length / 160)) === 0)
      .map((s) => s.bodies[body]?.position)
      .filter((v): v is Vec3 => !!v);
    const geo = new BufferGeometry().setFromPoints(
      points.map((p) => new Vector3(...p)),
    );
    return new Line(
      geo,
      new LineBasicMaterial({
        color: "#76d5e8",
        transparent: true,
        opacity: 0.52,
      }),
    );
  }, [samples, body]);
  return <primitive object={line} />;
}
function MeasuredGrid() {
  const geometry = useMemo(() => {
    const coords: number[] = [];
    for (let i = -8; i <= 8; i++) {
      const v = i * 0.1;
      coords.push(-0.8, v, 0.001, 0.8, v, 0.001, v, -0.8, 0.001, v, 0.8, 0.001);
    }
    const geo = new BufferGeometry();
    geo.setAttribute("position", new Float32BufferAttribute(coords, 3));
    return geo;
  }, []);
  return (
    <lineSegments geometry={geometry}>
      <lineBasicMaterial color="#60808d" opacity={0.18} transparent />
    </lineSegments>
  );
}
export default function Scene3D({
  geometries,
  samples,
  time,
  trajectory,
  playing,
  selected,
  onSelect,
}: {
  geometries: Geometry[];
  samples: Sample[];
  time: number;
  trajectory: boolean;
  playing: boolean;
  selected: string;
  onSelect: (name: string) => void;
}) {
  const { sample, next, alpha } = sampleAt(samples, time);
  const movingBody =
    Object.keys(sample?.bodies || {}).find((k) =>
      /gantry|gripper|end_effector|tool/.test(k),
    ) || "payload";
  return (
    <Canvas
      dpr={playing ? 0.8 : [1, 1.5]}
      shadows={!playing}
      camera={{
        position: [0.86, -1.03, 0.9],
        fov: 39,
        near: 0.01,
        far: 10,
        up: [0, 0, 1],
      }}
      gl={{ antialias: true, alpha: true, powerPreference: "low-power" }}
      onCreated={({ camera, gl }) => {
        camera.lookAt(0.02, 0.01, 0.1);
        gl.setClearColor("#151e27", 0);
      }}
      frameloop="demand"
      aria-hidden="true"
    >
      <ambientLight intensity={1.1} />
      <hemisphereLight args={["#c6edf5", "#203440", 1.7]} />
      <directionalLight
        position={[-0.7, -0.5, 1.5]}
        intensity={3.5}
        castShadow={!playing}
        shadow-mapSize={[1024, 1024]}
        shadow-camera-left={-0.8}
        shadow-camera-right={0.8}
        shadow-camera-top={0.8}
        shadow-camera-bottom={-0.8}
        shadow-normalBias={0.005}
      />
      <directionalLight
        position={[0.5, 0.7, 0.6]}
        intensity={2}
        color="#b6b6f7"
      />
      {geometries.map((g) => (
        <RenderGeometry
          key={g.name}
          geometry={g}
          sample={sample}
          next={next}
          alpha={alpha}
          selected={selected}
          onSelect={onSelect}
        />
      ))}
      <MeasuredGrid />
      {trajectory ? <Trajectory samples={samples} body={movingBody} /> : null}
      {sample?.contacts.slice(0, 12).map((c, i) =>
        Array.isArray(c.position) ? (
          <mesh key={i} position={c.position as Vec3}>
            <sphereGeometry args={[0.004, 12, 8]} />
            <meshBasicMaterial color="#ffb2aa" />
          </mesh>
        ) : null,
      )}
    </Canvas>
  );
}
