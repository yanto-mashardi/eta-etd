import Link from "next/link";
import { ShipWheel } from "lucide-react";
export default function Topbar({active}:{active:string}){return <div className="topbar"><div className="brand"><div className="brandMark"><ShipWheel size={25}/></div><div>Bengkalis–Pakning Ferry</div></div><nav className="nav"><Link className={active==="bengkalis"?"active":""} href="/bengkalis">Bengkalis</Link><Link className={active==="pakning"?"active":""} href="/pakning">Pakning</Link><Link className={active==="inspection"?"active":""} href="/inspection">Inspection</Link></nav></div>}
