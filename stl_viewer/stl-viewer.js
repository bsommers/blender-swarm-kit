/* ==========================================================================
   Zero-Dependency Binary STL 3D Viewer (WebGL Phong/TRON/Wire + Canvas 2D)
   Extracted from Operation Dumb Bunny into blender-swarm-kit.

   Usage:
     const viewer = createSTLViewer(canvasEl, stageEl, {
       baseColor: [0.38, 0.78, 0.96],
       renderMode: "shaded", // "shaded" | "tron" | "wire"
       autoOrbit: true,
       onStatus: (text) => { ... },
     });
     await viewer.loadUrl("model.stl");
     // or viewer.loadBuffer(arrayBuffer, "local.stl");
   ========================================================================== */

(function (global) {
  "use strict";

  function parseBinarySTL(buffer, opts) {
    const zUpToYUp = !opts || opts.zUpToYUp !== false;
    const view = new DataView(buffer);
    if (buffer.byteLength < 84) throw new Error("STL buffer too small");
    const triCount = view.getUint32(80, true);
    const expected = 84 + triCount * 50;
    if (expected > buffer.byteLength) {
      throw new Error(`Unexpected STL byte length (${buffer.byteLength} vs ${expected})`);
    }

    const positions = new Float32Array(triCount * 9);
    const normals = new Float32Array(triCount * 9);
    let minX = Infinity, minY = Infinity, minZ = Infinity;
    let maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity;

    let offset = 84;
    for (let i = 0; i < triCount; i++) {
      const x0 = view.getFloat32(offset + 12, true);
      const y0 = view.getFloat32(offset + 16, true);
      const z0 = view.getFloat32(offset + 20, true);

      const x1 = view.getFloat32(offset + 24, true);
      const y1 = view.getFloat32(offset + 28, true);
      const z1 = view.getFloat32(offset + 32, true);

      const x2 = view.getFloat32(offset + 36, true);
      const y2 = view.getFloat32(offset + 40, true);
      const z2 = view.getFloat32(offset + 44, true);
      offset += 50;

      const ax = x0, ay = zUpToYUp ? z0 : y0, az = zUpToYUp ? -y0 : z0;
      const bx = x1, by = zUpToYUp ? z1 : y1, bz = zUpToYUp ? -y1 : z1;
      const cx = x2, cy = zUpToYUp ? z2 : y2, cz = zUpToYUp ? -y2 : z2;

      const e1x = bx - ax, e1y = by - ay, e1z = bz - az;
      const e2x = cx - ax, e2y = cy - ay, e2z = cz - az;
      let nx = e1y * e2z - e1z * e2y;
      let ny = e1z * e2x - e1x * e2z;
      let nz = e1x * e2y - e1y * e2x;
      const len = Math.hypot(nx, ny, nz) || 1;
      nx /= len; ny /= len; nz /= len;

      const p = i * 9;
      positions[p] = ax; positions[p + 1] = ay; positions[p + 2] = az;
      positions[p + 3] = bx; positions[p + 4] = by; positions[p + 5] = bz;
      positions[p + 6] = cx; positions[p + 7] = cy; positions[p + 8] = cz;

      normals[p] = nx; normals[p + 1] = ny; normals[p + 2] = nz;
      normals[p + 3] = nx; normals[p + 4] = ny; normals[p + 5] = nz;
      normals[p + 6] = nx; normals[p + 7] = ny; normals[p + 8] = nz;

      if (ax < minX) minX = ax; if (ax > maxX) maxX = ax;
      if (bx < minX) minX = bx; if (bx > maxX) maxX = bx;
      if (cx < minX) minX = cx; if (cx > maxX) maxX = cx;
      if (ay < minY) minY = ay; if (ay > maxY) maxY = ay;
      if (by < minY) minY = by; if (by > maxY) maxY = by;
      if (cy < minY) minY = cy; if (cy > maxY) maxY = cy;
      if (az < minZ) minZ = az; if (az > maxZ) maxZ = az;
      if (bz < minZ) minZ = bz; if (bz > maxZ) maxZ = bz;
      if (cz < minZ) minZ = cz; if (cz > maxZ) maxZ = cz;
    }

    const midX = 0.5 * (minX + maxX);
    const midY = 0.5 * (minY + maxY);
    const midZ = 0.5 * (minZ + maxZ);
    const extent = Math.max(maxX - minX, maxY - minY, maxZ - minZ) || 1;
    const scale = 1.75 / extent;

    for (let i = 0; i < positions.length; i += 3) {
      positions[i] = (positions[i] - midX) * scale;
      positions[i + 1] = (positions[i + 1] - midY) * scale;
      positions[i + 2] = (positions[i + 2] - midZ) * scale;
    }

    return {
      triCount,
      positions,
      normals,
      bbox: { x: maxX - minX, y: maxY - minY, z: maxZ - minZ },
    };
  }

  function buildWireframeLines(positions) {
    const triCount = positions.length / 9;
    const lines = new Float32Array(triCount * 18);
    let dst = 0;
    for (let i = 0; i < positions.length; i += 9) {
      lines[dst++] = positions[i];     lines[dst++] = positions[i + 1]; lines[dst++] = positions[i + 2];
      lines[dst++] = positions[i + 3]; lines[dst++] = positions[i + 4]; lines[dst++] = positions[i + 5];
      lines[dst++] = positions[i + 3]; lines[dst++] = positions[i + 4]; lines[dst++] = positions[i + 5];
      lines[dst++] = positions[i + 6]; lines[dst++] = positions[i + 7]; lines[dst++] = positions[i + 8];
      lines[dst++] = positions[i + 6]; lines[dst++] = positions[i + 7]; lines[dst++] = positions[i + 8];
      lines[dst++] = positions[i];     lines[dst++] = positions[i + 1]; lines[dst++] = positions[i + 2];
    }
    return lines;
  }

  function createMat4Perspective(fovRad, aspect, near, far) {
    const f = 1.0 / Math.tan(fovRad / 2);
    const nf = 1 / (near - far);
    return new Float32Array([
      f / aspect, 0, 0, 0,
      0, f, 0, 0,
      0, 0, (far + near) * nf, -1,
      0, 0, 2 * far * near * nf, 0,
    ]);
  }

  function createModelView(yaw, pitch, dist) {
    const cy = Math.cos(yaw), sy = Math.sin(yaw);
    const cp = Math.cos(pitch), sp = Math.sin(pitch);
    return new Float32Array([
      cy, sp * sy, -cp * sy, 0,
      0, cp, sp, 0,
      sy, -sp * cy, cp * cy, 0,
      0, 0, -dist, 1,
    ]);
  }

  function createSTLViewer(canvas, stage, options) {
    const opts = Object.assign(
      {
        baseColor: [0.38, 0.78, 0.96],
        renderMode: "shaded",
        autoOrbit: !window.matchMedia("(prefers-reduced-motion: reduce)").matches,
        yaw: -0.42,
        pitch: 0.16,
        zoom: 2.5,
        onStatus: null,
      },
      options || {}
    );

    const state = {
      renderMode: opts.renderMode,
      autoOrbit: opts.autoOrbit,
      yaw: opts.yaw,
      pitch: opts.pitch,
      zoom: opts.zoom,
      baseColor: opts.baseColor,
      mesh: null,
      dirty: true,
    };

    let gl = null;
    try {
      gl = canvas.getContext("webgl", { antialias: true, alpha: true, preserveDrawingBuffer: true });
    } catch (_) {
      gl = null;
    }

    let glRes = null;
    let ctx2d = null;

    if (gl) {
      const vsSource = `
        attribute vec3 aPos;
        attribute vec3 aNorm;
        uniform mat4 uProj;
        uniform mat4 uMV;
        varying vec3 vNormal;
        varying vec3 vViewPos;
        varying vec3 vLocalPos;
        void main() {
          vec4 mvPos = uMV * vec4(aPos, 1.0);
          vViewPos = -mvPos.xyz;
          vNormal = normalize(mat3(uMV) * aNorm);
          vLocalPos = aPos;
          gl_Position = uProj * mvPos;
        }
      `;
      const fsSource = `
        precision mediump float;
        varying vec3 vNormal;
        varying vec3 vViewPos;
        varying vec3 vLocalPos;
        uniform vec3 uBaseColor;
        uniform int uMode;
        void main() {
          vec3 N = normalize(vNormal);
          if (!gl_FrontFacing) N = -N;
          vec3 V = normalize(vViewPos);
          vec3 L1 = normalize(vec3(0.55, 0.72, 0.85));
          vec3 L2 = normalize(vec3(-0.75, 0.25, 0.45));
          float diff1 = max(dot(N, L1), 0.0);
          float diff2 = max(dot(N, L2), 0.0);
          vec3 H = normalize(L1 + V);
          float spec = pow(max(dot(N, H), 0.0), 28.0);
          float fresnel = pow(1.0 - max(dot(N, V), 0.0), 2.4);

          if (uMode == 2) {
            gl_FragColor = vec4(0.0, 0.90, 1.0, 0.78);
            return;
          }
          if (uMode == 1) {
            float gx = abs(fract(vLocalPos.x * 12.0 - 0.5) - 0.5) / 0.06;
            float gy = abs(fract(vLocalPos.y * 12.0 - 0.5) - 0.5) / 0.06;
            float gridLine = 1.0 - clamp(min(gx, gy), 0.0, 1.0);
            vec3 core = vec3(0.03, 0.07, 0.16) + vec3(0.05, 0.18, 0.30) * diff1;
            vec3 neon = vec3(0.0, 0.90, 1.0) * (fresnel * 1.15 + gridLine * 0.52);
            gl_FragColor = vec4(core + neon, 1.0);
            return;
          }
          vec3 ambient = uBaseColor * 0.24 + vec3(0.03, 0.06, 0.12);
          vec3 key = uBaseColor * diff1 * 0.78 + vec3(0.98, 0.95, 0.92) * spec * 0.22;
          vec3 fill = vec3(0.45, 0.78, 0.98) * diff2 * 0.24;
          vec3 rim = vec3(0.15, 0.85, 1.0) * fresnel * 0.48;
          gl_FragColor = vec4(ambient + key + fill + rim, 1.0);
        }
      `;
      try {
        const compile = (type, src) => {
          const sh = gl.createShader(type);
          gl.shaderSource(sh, src);
          gl.compileShader(sh);
          if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(sh));
          return sh;
        };
        const prog = gl.createProgram();
        gl.attachShader(prog, compile(gl.VERTEX_SHADER, vsSource));
        gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, fsSource));
        gl.linkProgram(prog);
        if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error("link error");
        glRes = {
          prog,
          aPos: gl.getAttribLocation(prog, "aPos"),
          aNorm: gl.getAttribLocation(prog, "aNorm"),
          uProj: gl.getUniformLocation(prog, "uProj"),
          uMV: gl.getUniformLocation(prog, "uMV"),
          uBaseColor: gl.getUniformLocation(prog, "uBaseColor"),
          uMode: gl.getUniformLocation(prog, "uMode"),
          posBuf: gl.createBuffer(),
          normBuf: gl.createBuffer(),
          wireBuf: gl.createBuffer(),
          vertCount: 0,
          wireVertCount: 0,
        };
      } catch (_) {
        gl = null;
      }
    }
    if (!gl) ctx2d = canvas.getContext("2d");

    function uploadMesh(mesh) {
      if (!gl || !glRes) return;
      gl.bindBuffer(gl.ARRAY_BUFFER, glRes.posBuf);
      gl.bufferData(gl.ARRAY_BUFFER, mesh.positions, gl.STATIC_DRAW);
      gl.bindBuffer(gl.ARRAY_BUFFER, glRes.normBuf);
      gl.bufferData(gl.ARRAY_BUFFER, mesh.normals, gl.STATIC_DRAW);
      if (!mesh.wireLines) mesh.wireLines = buildWireframeLines(mesh.positions);
      gl.bindBuffer(gl.ARRAY_BUFFER, glRes.wireBuf);
      gl.bufferData(gl.ARRAY_BUFFER, mesh.wireLines, gl.STATIC_DRAW);
      glRes.vertCount = mesh.triCount * 3;
      glRes.wireVertCount = mesh.wireLines.length / 3;
    }

    function resize() {
      const rect = stage.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = Math.max(1, Math.floor(rect.width * dpr));
      const h = Math.max(1, Math.floor(rect.height * dpr));
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
        state.dirty = true;
      }
    }

    function drawGL() {
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.clearColor(0.02, 0.04, 0.09, 0.0);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      gl.enable(gl.DEPTH_TEST);
      gl.useProgram(glRes.prog);
      const proj = createMat4Perspective(Math.PI / 4, canvas.width / Math.max(1, canvas.height), 0.05, 50.0);
      const mv = createModelView(state.yaw, state.pitch, state.zoom);
      gl.uniformMatrix4fv(glRes.uProj, false, proj);
      gl.uniformMatrix4fv(glRes.uMV, false, mv);
      gl.uniform3fv(glRes.uBaseColor, state.baseColor);

      gl.bindBuffer(gl.ARRAY_BUFFER, glRes.posBuf);
      gl.enableVertexAttribArray(glRes.aPos);
      gl.vertexAttribPointer(glRes.aPos, 3, gl.FLOAT, false, 0, 0);
      gl.bindBuffer(gl.ARRAY_BUFFER, glRes.normBuf);
      gl.enableVertexAttribArray(glRes.aNorm);
      gl.vertexAttribPointer(glRes.aNorm, 3, gl.FLOAT, false, 0, 0);

      if (state.renderMode === "wire") {
        gl.enable(gl.POLYGON_OFFSET_FILL);
        gl.polygonOffset(1.0, 1.0);
        gl.uniform1i(glRes.uMode, 1);
        gl.drawArrays(gl.TRIANGLES, 0, glRes.vertCount);
        gl.disable(gl.POLYGON_OFFSET_FILL);
        gl.bindBuffer(gl.ARRAY_BUFFER, glRes.wireBuf);
        gl.vertexAttribPointer(glRes.aPos, 3, gl.FLOAT, false, 0, 0);
        gl.disableVertexAttribArray(glRes.aNorm);
        gl.uniform1i(glRes.uMode, 2);
        gl.drawArrays(gl.LINES, 0, glRes.wireVertCount);
      } else {
        gl.uniform1i(glRes.uMode, state.renderMode === "tron" ? 1 : 0);
        gl.drawArrays(gl.TRIANGLES, 0, glRes.vertCount);
      }
    }

    function draw2D() {
      const w = canvas.width, h = canvas.height;
      ctx2d.clearRect(0, 0, w, h);
      const pos = state.mesh.positions, nrm = state.mesh.normals;
      const cy = Math.cos(state.yaw), sy = Math.sin(state.yaw);
      const cp = Math.cos(state.pitch), sp = Math.sin(state.pitch);
      const fov = Math.min(w, h) * 0.92, cx = w * 0.5, cyScr = h * 0.5;
      const stride = state.mesh.triCount > 16000 ? 2 : 1;
      const visible = [];
      for (let t = 0; t < state.mesh.triCount; t += stride) {
        const i = t * 9;
        const nx0 = nrm[i], ny0 = nrm[i + 1], nz0 = nrm[i + 2];
        const rxn = nx0 * cy + nz0 * sy, rzn = -nx0 * sy + nz0 * cy;
        const ryn = ny0 * cp - rzn * sp, rzn2 = ny0 * sp + rzn * cp;
        if (rzn2 <= -0.05) continue;
        const sx = [], syArr = [];
        let zSum = 0;
        for (let k = 0; k < 3; k++) {
          const px = pos[i + k * 3], py = pos[i + k * 3 + 1], pz = pos[i + k * 3 + 2];
          const x1 = px * cy + pz * sy, z1 = -px * sy + pz * cy;
          const y2 = py * cp - z1 * sp, z2 = py * sp + z1 * cp;
          const denom = Math.max(0.2, state.zoom - z2);
          sx.push(cx + (x1 * fov) / denom);
          syArr.push(cyScr - (y2 * fov) / denom);
          zSum += z2;
        }
        visible.push({ z: zSum, sx, sy: syArr, light: Math.max(0.18, rxn * 0.45 + ryn * 0.65 + rzn2 * 0.62) });
      }
      visible.sort((a, b) => a.z - b.z);
      const bc = state.baseColor;
      for (const f of visible) {
        ctx2d.beginPath();
        ctx2d.moveTo(f.sx[0], f.sy[0]); ctx2d.lineTo(f.sx[1], f.sy[1]); ctx2d.lineTo(f.sx[2], f.sy[2]);
        ctx2d.closePath();
        ctx2d.fillStyle = `rgb(${Math.round(bc[0] * 255 * f.light)},${Math.round(bc[1] * 255 * f.light)},${Math.round(bc[2] * 255 * f.light)})`;
        ctx2d.fill();
      }
    }

    let dragging = false, lastX = 0, lastY = 0;
    stage.addEventListener("pointerdown", (e) => {
      dragging = true; lastX = e.clientX; lastY = e.clientY;
      stage.setPointerCapture(e.pointerId);
    });
    stage.addEventListener("pointermove", (e) => {
      if (!dragging) return;
      state.yaw += (e.clientX - lastX) * 0.009;
      state.pitch = Math.max(-1.35, Math.min(1.35, state.pitch + (e.clientY - lastY) * 0.008));
      lastX = e.clientX; lastY = e.clientY; state.dirty = true;
    });
    const stop = () => { dragging = false; };
    stage.addEventListener("pointerup", stop);
    stage.addEventListener("pointercancel", stop);
    stage.addEventListener("wheel", (e) => {
      e.preventDefault();
      state.zoom = Math.max(1.25, Math.min(5.2, state.zoom + Math.sign(e.deltaY) * 0.18));
      state.dirty = true;
    }, { passive: false });

    function loadBuffer(buffer, label) {
      const mesh = parseBinarySTL(buffer);
      state.mesh = mesh;
      if (gl) uploadMesh(mesh);
      state.dirty = true;
      if (opts.onStatus) {
        const eng = gl ? "WebGL" : "Canvas 2D";
        opts.onStatus(`${label || "STL"} · ${eng} · ${mesh.triCount.toLocaleString()} tris`);
      }
      return mesh;
    }

    async function loadUrl(url) {
      if (opts.onStatus) opts.onStatus(`Loading ${url}...`);
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return loadBuffer(await res.arrayBuffer(), url.split("/").pop());
    }

    function tick() {
      resize();
      if (state.mesh && (state.dirty || (state.autoOrbit && !dragging))) {
        if (state.autoOrbit && !dragging) state.yaw += 0.0065;
        if (gl) drawGL(); else if (ctx2d) draw2D();
        state.dirty = false;
      }
      requestAnimationFrame(tick);
    }
    window.addEventListener("resize", resize);
    resize();
    requestAnimationFrame(tick);

    return {
      loadUrl,
      loadBuffer,
      setRenderMode(m) { state.renderMode = m; state.dirty = true; },
      setAutoOrbit(on) { state.autoOrbit = Boolean(on); },
      setBaseColor(rgb) { state.baseColor = rgb; state.dirty = true; },
      resetCamera() { state.yaw = opts.yaw; state.pitch = opts.pitch; state.zoom = opts.zoom; state.dirty = true; },
    };
  }

  global.STLViewer = { parseBinarySTL, createSTLViewer };
})(window);
