import sourceConfig from '/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_OWNER_INPUT_INTEGRATION_MAC_20261010_R1/candidate/stage_r4_manager_r2_owner_input_r1_fused_r1/app/apps/web/vite.config.ts';

const root = '/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_OWNER_INPUT_INTEGRATION_MAC_20261010_R1/candidate/stage_r4_manager_r2_owner_input_r1_fused_r1/app/apps/web';
const cacheDir = '/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_OWNER_INPUT_INTEGRATION_MAC_20261010_R1/evidence/owner_input_r1/fusion_build/vite-cache';

export default {
  ...sourceConfig,
  root,
  cacheDir,
  build: {
    ...sourceConfig.build,
    emptyOutDir: true,
  },
};
