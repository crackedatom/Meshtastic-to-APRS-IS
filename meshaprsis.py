import logging
import socket
import datetime
import time
import configparser
import meshtastic
import meshtastic.tcp_interface
import pytz

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Read configuration from config.ini
config = configparser.ConfigParser()
config.read('config.ini')

serverHost = config['APRS']['serverHost']
serverPort = int(config['APRS']['serverPort'])
radioHostname = config['Meshtastic']['radioHostname']

node_db = {}


def get_meshtastic_nodedb():
    iface = meshtastic.tcp_interface.TCPInterface(radioHostname)
    if iface.nodes:
        now = int((datetime.datetime.now(datetime.UTC) - datetime.datetime(1970, 1, 1, tzinfo=pytz.utc)).total_seconds())
        timelimit = 60 * 60
        for node in iface.nodes.values():
            if node["user"]["id"] not in node_db and "lastHeard" in node and (now - node["lastHeard"]) < timelimit:
                user_id = node["user"]["id"]
                node_db[user_id] = {
                    "id": user_id,
                    "longName": node["user"]["longName"],
                    "shortName": node["user"]["shortName"].upper(),
                    "lastHeard": node["lastHeard"]
                }
                if "position" in node:
                    node_db[user_id]["position"] = {k: v for k, v in node["position"].items() if k in {"latitude", "longitude", "altitude", "time"}}
                    icon = "/["
                    aprs_str = aprs_pos(node["position"]["latitude"], node["position"]["longitude"], icon)
                    send_aprs_pos(aprs_str, node["user"]["shortName"], node["user"]["longName"])
                    logging.info(f"Added node {user_id} {node['user']['shortName']} Last heard {now - node['lastHeard']} seconds ago")
                    logging.info(aprs_str)
    iface.close()
    return node_db


def update_node_db():
    logging.info("Update start. Open connection.")
    iface = meshtastic.tcp_interface.TCPInterface(radioHostname)
    if iface.nodes:
        mesh = iface.nodes
        for node in node_db.values():
            if mesh[node["id"]]["lastHeard"] > node["lastHeard"]:
                node["lastHeard"] = mesh[node["id"]]["lastHeard"]
                logging.info(f"Node updated {node['longName']}")
            if "position" in node and "time" in node["position"] and mesh[node["id"]]["position"]["time"] > (node["position"]["time"] + 60):
                node["position"].update(mesh[node["id"]]["position"])
                icon = "/["
                aprs_str = aprs_pos(node["position"]["latitude"], node["position"]["longitude"], icon)
                send_aprs_pos(aprs_str, node["shortName"], node["longName"])
                logging.info(f"Node position updated {node['longName']}")
                logging.info(aprs_str)
    iface.close()
    logging.info("Update complete. Close connection.")


def dd_to_ddm(decimal_degrees):
    degrees = int(decimal_degrees)
    minutes = abs(decimal_degrees - degrees) * 60
    return degrees, minutes


def aprs_lat(dec):
    degrees, minutes = dd_to_ddm(dec)
    suffix = 'S' if degrees < 0 else 'N'
    return f"{abs(degrees):02d}{minutes:05.2f}{suffix}"


def aprs_lon(dec):
    degrees, minutes = dd_to_ddm(dec)
    suffix = 'W' if degrees < 0 else 'E'
    return f"{abs(degrees):03d}{minutes:05.2f}{suffix}"


def aprs_pos(lat, lon, icon):
    lat_str = aprs_lat(lat)
    lon_str = aprs_lon(lon)
    return f"{lat_str}{icon[0]}{lon_str}{icon[1]}"


def aprs_pass(callsign):
    callsign = callsign.split('-')[0].upper()
    code = 0x73e2
    for i, char in enumerate(callsign):
        code ^= ord(char) << (8 if not i % 2 else 0)
    return code & 0x7fff


def send_aprs_pos(pos, shortname, longname):
    address = f">APRS,TCPIP*,qAC,{shortname}:="
    aprsUser = shortname
    aprsPass = aprs_pass(shortname)
    callsign = shortname

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sSock:
            sSock.connect((serverHost, serverPort))
            sSock.send(f"user {aprsUser} pass {aprsPass} \n".encode())
            sSock.send(f"{callsign}{address}{pos}{longname}\n".encode())
            logging.info(f"Successfully sent APRS packet: {callsign}{address}{pos}{longname}")
    except Exception as e:
        logging.error(f"Error in APRS communication: {e}")


if __name__ == "__main__":
    while True:
        try:
            if not node_db:
                logging.info(f"Node DB is empty, downloading from node {radioHostname}")
                get_meshtastic_nodedb()
            for _ in range(6):
                update_node_db()
                time.sleep(60)
            logging.info("Refreshing node db")
            get_meshtastic_nodedb()
            time.sleep(60)
        except Exception as e:
            logging.error(f"An unexpected error occurred in the main loop: {e}")
