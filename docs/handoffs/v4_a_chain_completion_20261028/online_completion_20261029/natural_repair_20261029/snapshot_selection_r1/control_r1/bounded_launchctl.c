/* Fixed launchctl-only child supervisor. No shell, Python, arbitrary argv or PID input. */
#include <sys/types.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <fcntl.h>
#include <signal.h>
#include <unistd.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

struct call {const char *id; const char *role; char *const *argv;};
static char *const api_arm_print[]={"/bin/launchctl","print","gui/501/com.lexi.v4.api",NULL};
static char *const api_arm_debug[]={"/bin/launchctl","debug","gui/501/com.lexi.v4.api","--program","/bin/sleep","--","604800",NULL};
static char *const api_cleanup_print[]={"/bin/launchctl","print","gui/501/com.lexi.v4.api",NULL};
static char *const api_restore_before[]={"/bin/launchctl","debug","gui/501/com.lexi.v4.api","--program","/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python","--","-B","-m","apps.api.v4_api.run","--host","127.0.0.1","--port","8873","--stage-selection-root","/Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage/selection",NULL};
static char *const api_restore_after[]={"/bin/launchctl","debug","gui/501/com.lexi.v4.api","--program","/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python","--","-B","-m","apps.api.v4_api.run","--host","127.0.0.1","--port","8873","--stage-selection-root","/Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage/selection",NULL};
static char *const api_rollback_print[]={"/bin/launchctl","print","gui/501/com.lexi.v4.api",NULL};
static char *const api_rollback_debug[]={"/bin/launchctl","debug","gui/501/com.lexi.v4.api","--program","/bin/sleep","--","604800",NULL};
static char *const collector_arm_print[]={"/bin/launchctl","print","gui/501/com.lexi.v4.runtime-graph",NULL};
static char *const collector_arm_debug[]={"/bin/launchctl","debug","gui/501/com.lexi.v4.runtime-graph","--program","/bin/sleep","--","604800",NULL};
static char *const collector_cleanup_print[]={"/bin/launchctl","print","gui/501/com.lexi.v4.runtime-graph",NULL};
static char *const collector_restore_before[]={"/bin/launchctl","debug","gui/501/com.lexi.v4.runtime-graph","--program","/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/retirement-collector-20261028/venvs/v4-mac/bin/python","--","-B","/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/v4-retirement-20261028-collector/app/ops/collect_runtime_graph.py","--events","--data-root","/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data","--config","/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-snapshot-recovery-20261029-r1-graph/runtime-graph-config.json",NULL};
static char *const collector_restore_after[]={"/bin/launchctl","debug","gui/501/com.lexi.v4.runtime-graph","--program","/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/retirement-collector-20261028/venvs/v4-mac/bin/python","--","-B","/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/v4-retirement-20261028-collector/app/ops/collect_runtime_graph.py","--events","--data-root","/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data","--config","/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-snapshot-selection-20261029-r1-graph/runtime-graph-config.json",NULL};
static char *const stage_arm_print[]={"/bin/launchctl","print","gui/501/com.lexi.stage-center.scheduler",NULL};
static char *const stage_arm_debug[]={"/bin/launchctl","debug","gui/501/com.lexi.stage-center.scheduler","--program","/bin/sleep","--","604800",NULL};
static char *const stage_cleanup_print[]={"/bin/launchctl","print","gui/501/com.lexi.stage-center.scheduler",NULL};
static char *const stage_restore_before[]={"/bin/launchctl","debug","gui/501/com.lexi.stage-center.scheduler","--program","/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python","--","-B","/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-snapshot-recovery-20261029-r1-stage/app/ops/run_stage_center_nodes.py","--config","/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-snapshot-recovery-20261029-r1-stage/app/stage_center_tick_config.json",NULL};
static char *const stage_restore_after[]={"/bin/launchctl","debug","gui/501/com.lexi.stage-center.scheduler","--program","/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python","--","-B","/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-snapshot-selection-20261029-r1-stage/app/ops/run_stage_center_nodes.py","--config","/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-snapshot-selection-20261029-r1-stage/app/stage_center_tick_config.json",NULL};
static char *const precapture_arm_print[]={"/bin/launchctl","print","gui/501/com.lexi.stage-center.a-opening-precapture",NULL};
static char *const precapture_arm_debug[]={"/bin/launchctl","debug","gui/501/com.lexi.stage-center.a-opening-precapture","--program","/bin/sleep","--","604800",NULL};
static char *const precapture_cleanup_print[]={"/bin/launchctl","print","gui/501/com.lexi.stage-center.a-opening-precapture",NULL};
static char *const precapture_restore_before[]={"/bin/launchctl","debug","gui/501/com.lexi.stage-center.a-opening-precapture","--program","/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python","--","-B","/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-snapshot-recovery-20261029-r1-stage/app/ops/run_stage_center_nodes.py","--config","/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-snapshot-recovery-20261029-r1-stage/app/stage_center_tick_config.json","--node","PRECAPTURE_A_0925",NULL};
static char *const precapture_restore_after[]={"/bin/launchctl","debug","gui/501/com.lexi.stage-center.a-opening-precapture","--program","/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python","--","-B","/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-snapshot-selection-20261029-r1-stage/app/ops/run_stage_center_nodes.py","--config","/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-snapshot-selection-20261029-r1-stage/app/stage_center_tick_config.json","--node","PRECAPTURE_A_0925",NULL};
static const struct call calls[]={{"api_arm_print","api",api_arm_print},{"api_arm_debug","api",api_arm_debug},{"api_cleanup_print","api",api_cleanup_print},{"api_restore_before","api",api_restore_before},{"api_restore_after","api",api_restore_after},{"api_rollback_print","api",api_rollback_print},{"api_rollback_debug","api",api_rollback_debug},{"collector_arm_print","collector",collector_arm_print},{"collector_arm_debug","collector",collector_arm_debug},{"collector_cleanup_print","collector",collector_cleanup_print},{"collector_restore_before","collector",collector_restore_before},{"collector_restore_after","collector",collector_restore_after},{"stage_arm_print","stage",stage_arm_print},{"stage_arm_debug","stage",stage_arm_debug},{"stage_cleanup_print","stage",stage_cleanup_print},{"stage_restore_before","stage",stage_restore_before},{"stage_restore_after","stage",stage_restore_after},{"precapture_arm_print","precapture",precapture_arm_print},{"precapture_arm_debug","precapture",precapture_arm_debug},{"precapture_cleanup_print","precapture",precapture_cleanup_print},{"precapture_restore_before","precapture",precapture_restore_before},{"precapture_restore_after","precapture",precapture_restore_after}};
static volatile sig_atomic_t interrupted=0;
static void interrupted_by(int sig){interrupted=sig;}
static double monotime(void){struct timespec t;if(clock_gettime(CLOCK_MONOTONIC,&t))_exit(125);return t.tv_sec+t.tv_nsec/1e9;}
static double walltime(void){struct timespec t;if(clock_gettime(CLOCK_REALTIME,&t))_exit(125);return t.tv_sec+t.tv_nsec/1e9;}
static int record(int dir,const char *name,const char *value,int exclusive){
 int fd=openat(dir,name,O_WRONLY|O_CREAT|O_NOFOLLOW|(exclusive?O_EXCL:O_APPEND),0644);
 if(fd<0)return -1;
 size_t n=strlen(value);ssize_t written=write(fd,value,n);int ok=written==(ssize_t)n&&fsync(fd)==0;
 close(fd);return ok?0:-1;
}
static int unknown(int dir,const struct call *c,const char *reason){
 char name[128],value[256];snprintf(value,sizeof(value),"UNKNOWN %s %s\n",c->id,reason);
 snprintf(name,sizeof(name),"%s.cli.UNKNOWN",c->role);
 int a=record(dir,name,value,0),b=record(dir,"CLI_UNKNOWN",value,0);
 return a||b?-1:0;
}
int main(int argc,char **argv){
 if(argc!=4||geteuid()!=0)return 125;
 const struct call *c=NULL;for(size_t i=0;i<sizeof(calls)/sizeof(calls[0]);i++)if(!strcmp(argv[1],calls[i].id)){c=&calls[i];break;}
 if(!c)return 125;
 const char *prefix="/private/var/tmp/v4-a-chain-nextspawn-";
 if(strncmp(argv[3],prefix,strlen(prefix))||strlen(argv[3])!=strlen(prefix)+32)return 125;
 for(const char *x=argv[3]+strlen(prefix);*x;x++)if(!strchr("0123456789abcdef",*x))return 125;
 char *end=NULL;errno=0;double deadline_epoch=strtod(argv[2],&end);
 if(errno||!end||*end||deadline_epoch<=0)return 125;
 int dir=open(argv[3],O_RDONLY|O_DIRECTORY|O_NOFOLLOW);struct stat st;
 if(dir<0||fstat(dir,&st)||st.st_uid!=0||(st.st_mode&0022))return 125;
 char intent[128],status[128];snprintf(intent,sizeof(intent),"%s.cli.intent",c->id);snprintf(status,sizeof(status),"%s.cli.status",c->id);
 if(record(dir,intent,"INTENT\n",1)){unknown(dir,c,"EXISTING_OR_UNWRITABLE_INTENT_NO_REPLAY");return 125;}
 double remaining=deadline_epoch-walltime();double budget=remaining<3.0?remaining:3.0;
 if(!(budget>0)){unknown(dir,c,"DEADLINE_BEFORE_SPAWN");record(dir,status,"UNKNOWN DEADLINE_BEFORE_SPAWN\n",1);return 124;}
 double deadline=monotime()+budget;
 struct sigaction sa;memset(&sa,0,sizeof(sa));sa.sa_handler=interrupted_by;sigemptyset(&sa.sa_mask);
 sigaction(SIGTERM,&sa,NULL);sigaction(SIGINT,&sa,NULL);sigaction(SIGHUP,&sa,NULL);
 pid_t child=fork();
 if(child<0){unknown(dir,c,"FORK_FAILED");return 125;}
 if(child==0){signal(SIGTERM,SIG_DFL);signal(SIGINT,SIG_DFL);signal(SIGHUP,SIG_DFL);execv("/bin/launchctl",c->argv);_exit(127);}
 int result=0;pid_t done=0;
 for(;;){
  /* waitpid is the only owner/reap authority; after it returns child we never signal. */
  done=waitpid(child,&result,WNOHANG);
  if(done<0&&errno!=EINTR){unknown(dir,c,"WAIT_OWNERSHIP_UNKNOWN_NO_SIGNAL");return 125;}
  if(interrupted||monotime()>=deadline)break;
  if(done==child){
   int rc=WIFEXITED(result)?WEXITSTATUS(result):125;char value[64];snprintf(value,sizeof(value),"EXIT %d\n",rc);
   if(record(dir,status,value,1)){unknown(dir,c,"RESULT_NOT_DURABLE");return 125;}return rc;
  }
  struct timespec pause={0,10000000};nanosleep(&pause,NULL);
 }
 /* Durable UNKNOWN precedes signals. A late successful exit can never change it. */
 if(unknown(dir,c,interrupted?"INTERRUPTED":"TIMEOUT")||record(dir,status,"UNKNOWN NO_REPLAY\n",1))return 125;
 if(done!=child){
  /* A direct unreaped child retains its PID: no service PID, group or external PID. */
  kill(child,SIGTERM);
  done=waitpid(child,&result,WNOHANG);
  if(done==0){kill(child,SIGKILL);done=waitpid(child,&result,WNOHANG);}
 }
 record(dir,"CLI_UNKNOWN",done==child?"CLI_REAPED_SERVER_OUTCOME_UNKNOWN\n":"STOP_CLI_UNREAPED_KERNEL_OR_LAUNCHD_UNKNOWN\n",0);
 /* Never block in wait after deadline. Kernel/filesystem uninterruptibility remains STOP. */
 return 124;
}
