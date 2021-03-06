#!/usr/bin/env python3
import psycopg2
import os, sys, stat
from multiprocessing import Pool, get_context
from datetime import datetime, timedelta
import time, string
from pandas import DataFrame, to_datetime, Timedelta, Timestamp, concat, read_sql
#import pandas
#pandas.set_option('display.max_rows', 100)

amd64_pmc_eventmap = { 0x43ff03 : "FLOPS,W=48", 0x4300c2 : "BRANCH_INST_RETIRED,W=48", 0x4300c3: "BRANCH_INST_RETIRED_MISS,W=48", 
                       0x4308af : "DISPATCH_STALL_CYCLES1,W=48", 0x43ffae :"DISPATCH_STALL_CYCLES0,W=48" }

amd64_df_eventmap = { 0x403807 : "MBW_CHANNEL_0,W=48,U=64B", 0x403847 : "MBW_CHANNEL_1,W=48,U=64B", 0x403887 : "MBW_CHANNEL_2,W=48,U=64B" , 
                      0x4038c7 : "MBW_CHANNEL_3,W=48,U=64B", 0x433907 : "MBW_CHANNEL_4,W=48,U=64B", 0x433947 : "MBW_CHANNEL_5,W=48,U=64B", 
                      0x433987 : "MBW_CHANNEL_6,W=48,U=64B", 0x4339c7 : "MBW_CHANNEL_7,W=48,U=64B" }

intel_8pmc3_eventmap = { 0x4301c7 : 'FP_ARITH_INST_RETIRED_SCALAR_DOUBLE,W=48,U=1',      0x4302c7 : 'FP_ARITH_INST_RETIRED_SCALAR_SINGLE,W=48,U=1',
                         0x4304c7 : 'FP_ARITH_INST_RETIRED_128B_PACKED_DOUBLE,W=48,U=2', 0x4308c7 : 'FP_ARITH_INST_RETIRED_128B_PACKED_SINGLE,W=48,U=4',
                         0x4310c7 : 'FP_ARITH_INST_RETIRED_256B_PACKED_DOUBLE,W=48,U=4', 0x4320c7 : 'FP_ARITH_INST_RETIRED_256B_PACKED_SINGLE,W=48,U=8',
                         0x4340c7 : 'FP_ARITH_INST_RETIRED_512B_PACKED_DOUBLE,W=48,U=8', 0x4380c7 : 'FP_ARITH_INST_RETIRED_512B_PACKED_SINGLE,W=48,U=16', 
                         "FIXED_CTR0" : 'INST_RETIRED,W=48', "FIXED_CTR1" : 'APERF,W=48', "FIXED_CTR2" : 'MPERF,W=48' }

intel_skx_imc_eventmap = {0x400304 : "CAS_READS,W=48", 0x400c04 : "CAS_WRITES,W=48", 0x400b01 : "ACT_COUNT,W=48", 0x400102 : "PRE_COUNT_MISS,W=48"}

"""
{ time : 1628783584.433181, host : amd-1, jobid : 101, type : amd64_rapl, device : 0, event : MSR_CORE_ENERGY_STAT, unit : mJ, width : 32, value : 1668055930 } 

"""


exclude_typs = ["block", "ib", "ib_sw", "intel_skx_cha", "mdc", "numa", "osc", "proc", "ps", "sysv_shm", "tmpfs", "vfs", "vm"]


CONNECTION = "dbname=taccstats user=postgres port=5433"

query_create_hostdata_table = """CREATE TABLE IF NOT EXISTS host_data (
                                           time  TIMESTAMPTZ NOT NULL,
                                           host  VARCHAR(64),
                                           jid   VARCHAR(32),
                                           type  VARCHAR(32),
                                           event VARCHAR(64),
                                           unit  VARCHAR(16),                                            
                                           value real,
                                           diff  real,
                                           arc   real,
                                           UNIQUE (time, host, type, event)
                                           );"""

query_create_hostdata_hypertable = """CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE; 
                                      SELECT create_hypertable('host_data', 'time', if_not_exists => TRUE, chunk_time_interval => INTERVAL '1 day');
                                      CREATE INDEX ON host_data (host, time DESC);
                                      CREATE INDEX ON host_data (jid, time DESC);"""

query_create_compression = """ALTER TABLE host_data SET (timescaledb.compress, timescaledb.compress_orderby = 'time DESC', timescaledb.compress_segmentby = 'host,jid,type,event');
                              SELECT add_compression_policy('host_data', INTERVAL '1d');"""

conn = psycopg2.connect(CONNECTION)
print(conn.server_version)
with conn.cursor() as cur:
    #cur.execute("DROP TABLE IF EXISTS host_data;")
    #cur.execute(query_create_hostdata_table)
    #cur.execute(query_create_hostdata_hypertable)
    #cur.execute(query_create_compression)
    cur.execute("SELECT pg_size_pretty(pg_database_size('taccstats'));")
    print(cur.fetchall())
    cur.execute("SELECT chunk_name,before_compression_total_bytes,after_compression_total_bytes FROM chunk_compression_stats('host_data');")
    print(cur.fetchall())
    cur.execute("SELECT * FROM timescaledb_information.chunks WHERE hypertable_name = 'host_data';")
    print(cur.fetchall())
    conn.commit()
    cur.close()
conn.close()

def process(stats_file):
    
    sql = "select time from host_data where host = '{0}' order by time desc limit 1;".format(stats_file.split('/')[-2])

    conn = psycopg2.connect(CONNECTION)

    with conn.cursor() as cur:
        cur.execute(sql)
        ltime = cur.fetchall()
        if len(ltime) > 0: ltime = float(ltime[0][0].timestamp())
        else: ltime = 0

    if ltime > time.time() - 3600: 
        print(stats_file, " sync current")
        return stats_file  
     
    with open(stats_file, 'r') as fd:
        lines = fd.readlines()

    schema = {}
    stats  = []
    insert = False
    start = time.time()
    for line in lines: 
        if not line[0]: continue

        if line[0].isalpha() and insert:
            typ, dev, vals = line.split(maxsplit = 2)        
            vals = vals.split()
            if typ in exclude_typs: continue

            # Mapping hardware counters to events 
            if typ == "amd64_pmc" or typ == "amd64_df" or typ == "intel_8pmc3" or typ == "intel_skx_imc":
                if typ == "amd64_pmc": eventmap = amd64_pmc_eventmap
                if typ == "amd64_df": eventmap = amd64_df_eventmap
                if typ == "intel_8pmc3": eventmap = intel_8pmc3_eventmap
                if typ == "intel_skx_imc": eventmap = intel_skx_imc_eventmap
                n = {}
                rm_idx = []
                schema_mod = []*len(schema[typ])

                for idx, eve in enumerate(schema[typ]):
            
                    eve = eve.split(',')[0]
                    if "CTL" in eve:
                        try:
                            n[eve.lstrip("CTL")] = eventmap[int(vals[idx])]
                        except:
                            n[eve.lstrip("CTL")] = "OTHER"                    
                        rm_idx += [idx]
                    
                    elif "FIXED_CTR" in eve: 
                        schema_mod += [eventmap[eve]]

                    elif "CTR" in eve:
                        schema_mod += [n[eve.lstrip("CTR")]]
                    else:
                        schema_mod += [eve]
                
                for idx in sorted(rm_idx, reverse = True): del vals[idx]
                vals = dict(zip(schema_mod, vals))
            else:
                # Software counters are not programmable and do not require mapping
                vals = dict(zip(schema[typ], vals))

            rec  =  { **tags, "typ" : typ, "dev" : dev }   

            for eve, val in vals.items():
                eve = eve.split(',')
                width = 64
                mult = 1
                unit = "#"
                
                for ele in eve[1:]:                    
                    if "W=" in ele: width = int(ele.lstrip("W="))
                    if "U=" in ele: 
                        ele = ele.lstrip("U=")
                        try:    mult = float(''.join(filter(str.isdigit, ele)))
                        except: pass
                        try:    unit = ''.join(filter(str.isalpha, ele))
                        except: pass
                
                stats += [ { **rec, "eve" : eve[0], "val" : float(val), "wid" : width, "mult" : mult, "unit" : unit } ]
            
        elif line[0].isdigit():
            t, jid, host = line.split()

            if ltime < float(t): 
                insert = True
            else:
                insert = False

            tags = { "time" : float(t), "host" : host, "jid" : jid }
        elif line[0] == '!':
            label, events = line.split(maxsplit = 1)
            typ, events = label[1:], events.split()
            schema[typ] = events 
        
    stats = DataFrame.from_records(stats)
    if stats.empty: 
        print(stats_file + " completed")
        return(stats_file)

    # compute difference between time adjacent stats
    stats["dif"] = (stats.groupby(["host", "jid", "typ", "dev", "eve"])["val"].diff()).fillna(0)

    # correct stats for rollover and units
    stats["dif"].mask(stats["dif"] < 0, 2**stats["wid"] + stats["dif"], inplace = True)
    stats["dif"] = stats["dif"] * stats["mult"]
    del stats["wid"], stats["mult"]

    # aggregate over devices
    stats = stats.groupby(["time", "host", "jid", "typ", "eve", "unit"]).sum().reset_index()            

    # compute average rate of change
    deltat = stats.groupby(["host", "jid", "typ", "eve"])["time"].diff().fillna(0)
    stats["arc"] = (stats["dif"]/deltat).fillna(0)    

    stats["time"] = to_datetime(stats["time"], unit = 's').dt.tz_localize('UTC').dt.tz_convert('US/Central')

    print("processing time for {0} {1:.1f}s".format(stats_file, time.time() - start))

    sqltime = time.time()
    sql = """
    COPY host_data
    FROM '{0}.csv' 
    DELIMITER ',' CSV;
    """.format(stats_file)
    
    with conn.cursor() as cur:
        stats.to_csv('{0}.csv'.format(stats_file), index=False, header=False)        
        os.chmod('{0}.csv'.format(stats_file), 0o666) 
        cur.execute(sql)
        try:
            conn.commit()
            os.remove('{0}.csv'.format(stats_file))
            print("sql insert time for {0} {1:.1f}s".format(stats_file, time.time() - sqltime))
        except:
            print(stats_file, " sync failed")        

    conn.close()
    return stats_file

#################################################################
startdate = datetime.strptime(sys.argv[1], "%Y-%m-%d")
try:
    enddate   = datetime.strptime(sys.argv[2], "%Y-%m-%d")
except:
    enddate = startdate + timedelta(days = 1)
print("Start Date: ", startdate)
print("Start End:  ",  enddate)
#################################################################

# Parse and convert raw stats files to pandas dataframe
start = time.time()
directory = "/fstats/archive"

stats_files = []
for entry in os.scandir(directory):
    if entry.is_file() or not entry.name.startswith("c"): continue
    for stats_file in os.scandir(entry.path):
        if not stats_file.is_file() or stats_file.name.startswith('.'): continue
        if stats_file.name.startswith("current"): continue
        try:
            fdate = datetime.fromtimestamp(int(stats_file.name))
        except: continue
        if  fdate < startdate - timedelta(days = 1) or fdate > enddate: continue
        stats_files += [stats_file.path]

print("Number of host stats files to process = ", len(stats_files))


with Pool(processes = 32) as pool:
    for i in pool.imap_unordered(process, stats_files):
        print("[{0:.1f}%] completed".format(100*stats_files.index(i)/len(stats_files)))

"""
for i in map(process, stats_files):
    continue
"""



print("loading time", time.time() - start)
#conn.close()
