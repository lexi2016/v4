/** Static compile seam only. The shared real app API module overrides this in Mac. */
export type AnnouncementAnalysisObject = Record<string, unknown>;
export interface ManagerAnnouncementAnalysis { target_trade_date:string; publication_date:string; date_selection_basis:string; source_catalog:AnnouncementAnalysisObject; analysis:AnnouncementAnalysisObject; owner_import_receipt?:unknown; consumption_validation?:unknown }
