import { createApp } from "vue";
import Workbench from "../manager-workbench/Workbench.vue";

// Candidate mount only. Mac integration owns the app-wide activation / rollback.
createApp(Workbench).mount("#manager-selection");
