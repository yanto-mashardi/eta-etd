export type Vessel={
  mmsi:number;shipname?:string;latitude?:number;longitude?:number;sog?:number;
  operational_state?:string;current_port?:string;destination_port?:string;nearest_berth?:string;
  berth_distance_nm?:number|null;eta_baseline_min?:number|null;eta_corrected_min?:number|null;
  eta_timestamp?:string|null;turnaround_corrected_min?:number|null;etd_timestamp?:string|null;
  data_quality?:string
};
export type VehicleState={
  car_queue_current?:number;motor_queue_current?:number;car_in_total?:number;motor_in_total?:number;
  car_out_total?:number;motor_out_total?:number;loaded_car_total?:number;loaded_motor_total?:number;
  updated_at?:string|null;counting_algorithm?:string;[key:string]:any
};
export type CurrentState={
  generated_at?:string;ais_updated_at?:string;cctv_updated_at?:string|null;ml1_status?:string;ml2_status?:string;
  vessels?:Vessel[];berths?:Record<string,{status:string;mmsi?:number;shipname?:string}>;
  vehicle_bengkalis?:VehicleState;vehicle_pakning?:VehicleState;diagnostics?:Record<string,any>
};
export type CctvPayload={port:string;camera_id?:string;available?:boolean;updated_at?:string|null;state?:VehicleState;
  raw_rtsp_url?:string|null;yolo_rtsp_url?:string|null;raw_webrtc_url?:string|null;yolo_webrtc_url?:string|null;
  raw_hls_url?:string|null;yolo_hls_url?:string|null
};
