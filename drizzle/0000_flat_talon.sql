CREATE TABLE `strategy_parameters` (
	`user_id` text PRIMARY KEY NOT NULL,
	`parameters_json` text NOT NULL,
	`updated_at` integer NOT NULL
);
