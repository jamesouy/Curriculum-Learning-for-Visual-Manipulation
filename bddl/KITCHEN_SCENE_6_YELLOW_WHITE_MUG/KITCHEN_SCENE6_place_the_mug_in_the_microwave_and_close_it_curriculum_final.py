import numpy as np

base_bddl = """
(define (problem LIBERO_Kitchen_Tabletop_Manipulation)
  (:domain robosuite)
  (:language put the white yellow mug in the microwave and close it)
    (:regions
      (microwave_init_region
          (:target kitchen_table)
          (:ranges (
              (-0.01 0.33999999999999997 0.01 0.36)
            )
          )
          (:yaw_rotation (
              (0 0)
            )
          )
      )
      (white_yellow_mug_init_region
          (:target kitchen_table)
          (:ranges (
              (-0.025 -0.025 0.025 0.025)
            )
          )
          (:yaw_rotation (
              (0.0 0.0)
            )
          )
      )
      (porcelain_mug_init_region
          (:target kitchen_table)
          (:ranges (
              (-0.125 -0.275 -0.07500000000000001 -0.225)
            )
          )
          (:yaw_rotation (
              (0.0 0.0)
            )
          )
      )
      (porcelain_mug_front_region
          (:target kitchen_table)
          (:ranges (
              (-0.05 -0.3 0.05 -0.2)
            )
          )
          (:yaw_rotation (
              (0.0 0.0)
            )
          )
      )
      (top_side
          (:target microwave_1)
      )
      (heating_region
          (:target microwave_1)
      )
      (handle_region
          (:target microwave_1)
      )
    )

  (:fixtures
    kitchen_table - kitchen_table
    microwave_1 - microwave
  )

  (:objects
    porcelain_mug_1 - porcelain_mug
    white_yellow_mug_1 - white_yellow_mug
  )

  (:obj_of_interest
    white_yellow_mug_1
    microwave_1
  )

  (:init
    (On porcelain_mug_1 kitchen_table_porcelain_mug_init_region)
    (On white_yellow_mug_1 kitchen_table_white_yellow_mug_init_region)
    (On microwave_1 kitchen_table_microwave_init_region)
    (Open microwave_1)
  )

  (:goal
    (And {})
  )

)
"""

def place_the_mug_and_close_the_microwave():
	return base_bddl.format("(And (In white_yellow_mug_1 microwave_1_heating_region) (Close microwave_1 1.0))")
