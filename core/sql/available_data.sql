select max(fx.eod_date) max_date, d.ts_shortname, d.ts_name, d.ts_source
	from mdh.fx_ts fx
	left join mdh.ts_dict d
	on fx.ts_id = d.ts_id and ts_source = :ts_source
	where d.ts_shortname is not null
	group by d.ts_shortname, d.ts_name, d.ts_source;