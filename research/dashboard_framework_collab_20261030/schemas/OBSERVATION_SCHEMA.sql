CREATE TABLE `research_observation_snapshots` (
	`sha256` text PRIMARY KEY NOT NULL,
	`parent_admission_sha256` text NOT NULL,
	`source_date` text NOT NULL,
	`observation_date` text NOT NULL,
	`daily_contract_sha256` text NOT NULL,
	`identity_set_sha256` text NOT NULL,
	`slot` text NOT NULL,
	`source_asof_min` text NOT NULL,
	`source_asof_max` text NOT NULL,
	`observed_upper_bound_max` text NOT NULL,
	`bytes` integer NOT NULL,
	`committed_at` text NOT NULL,
	FOREIGN KEY (`parent_admission_sha256`) REFERENCES `research_admissions`(`sha256`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE INDEX `research_observation_parent_day_idx` ON `research_observation_snapshots` (`parent_admission_sha256`,`observation_date`);