# 原V4界面与独立V5 API入口

沿用现役V4的构建产物，不重写Vue页面。gateway启动时读取明确静态清单，逐文件SHA验证并固定到内存，原HTML/JS/CSS字节不改。不同路径只服务清单内文件，不列目录、不中转到V4；GET /api仍由独立路由表决定。没有连接的API会明确返回错误，不能当已完成业务。

启动参数：api_gateway原--config/--port，加--frontend-root和--frontend-manifest（两者成对）。清单是相对路径→SHA256。可先用空modules/routes展示原页面和未连接状态，随后逐模块接线；此阶段不能宣称真实选股、每日调度或全页面功能通过。

module_api提供每模块一个只读服务进程：独立module_id、release_id、data_root及route白名单。数据根必须有对应.v5-module-root标记；root目录FD固定，记录目录和文件使用dir_fd/NOFOLLOW、文件NONBLOCK并拒绝特殊文件。每个响应记录绑定module/release/path/query/payload摘要，保留原API字段，错误不是空成功。该服务没有collector、计算或writer权限；它不认证source_input_sha256背后的真实性。

原模块owner完成数据/状态后，应独立物化此模块的原API响应。未有记录时503/CANNOT_CONFIRM；版本或摘要不符409。原payload按JSON重编码，承诺字段保留，不声称原传输字节不变。

source生成、worker和API服务应分别固定模块版本，不向同一个进程导入所有业务。网关与每个module_api分别启动；目前没有自动部署或完整业务producer接线。

本批网关14项（此前12通过，新增2未运行）及模块API11项定义，等待Mac独立测试。root仅AST/静态检查。不触碰V4的8873，不停止现役服务，不改变用户屏幕设置。
