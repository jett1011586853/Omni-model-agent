using UnityEngine;

/// <summary>
/// 玩家控制器 - CS:GO 风格第一人称移动和交互
/// 实现：移动、瞄准、蹲下、冲刺、反身移动、急停射击
/// </summary>
public class PlayerController : MonoBehaviour
{
    [Header("移动设置")]
    [Tooltip("正常移动速度")]
    public float walkSpeed = 5f;
    
    [Tooltip("冲刺速度")]
    public float sprintSpeed = 9f;
    
    [Tooltip("蹲下速度")]
    public float crouchSpeed = 3f;
    
    [Tooltip("移动加速度")]
    public float acceleration = 15f;
    
    [Tooltip("移动减速度")]
    public float deceleration = 20f;
    
    [Header("跳跃设置")]
    [Tooltip("跳跃力")]
    public float jumpForce = 7f;
    
    [Tooltip("空中跳跃力")]
    public float airJumpForce = 5f;
    
    [Header("瞄准设置")]
    [Tooltip("瞄准灵敏度")]
    public float aimSensitivity = 2f;
    
    [Tooltip("开火时视角晃动幅度")]
    public float aimRecoil = 0.05f;
    
    [Header("蹲下设置")]
    [Tooltip("站立高度")]
    public float standHeight = 1.8f;
    
    [Tooltip("蹲下高度")]
    public float crouchHeight = 1.0f;
    
    [Header("冲刺设置")]
    [Tooltip("冲刺冷却时间")]
    public float sprintCooldown = 2f;
    
    [Tooltip("冲刺持续时间")]
    public float sprintDuration = 3f;

    // 组件引用
    private CharacterController characterController;
    private Camera playerCamera;
    private Animator playerAnimator;

    // 状态变量
    private Vector3 velocity;
    private bool isGrounded;
    private bool isAiming;
    private bool isCrouching;
    private bool isSprinting;
    private bool canSprint = true;
    private float sprintTimer;
    private float currentHeight;
    private Vector3 moveDirection;

    // 移动状态
    private bool isMoving;
    private Vector3 lastMoveDirection;

    void Start()
    {
        // 获取组件引用
        characterController = GetComponent<CharacterController>();
        playerCamera = GetComponentInChildren<Camera>();
        playerAnimator = GetComponentInChildren<Animator>();
        
        // 初始化高度
        currentHeight = standHeight;
        
        // 设置相机偏移
        if (playerCamera != null)
        {
            playerCamera.transform.localPosition = new Vector3(0, 0.1f, 0);
        }
    }

    void Update()
    {
        HandleInput();
        HandleMovement();
        HandleCrouching();
        HandleSprinting();
        ApplyGravity();
        UpdateAnimator();
    }

    /// <summary>
    /// 处理输入
    /// </summary>
    private void HandleInput()
    {
        // 瞄准 (右键)
        isAiming = Input.GetMouseButton(1);
        
        // 蹲下 (Ctrl)
        if (Input.GetKeyDown(KeyCode.LeftControl))
        {
            ToggleCrouch();
        }
        
        // 冲刺 (Shift)
        if (Input.GetKeyDown(KeyCode.LeftShift) && canSprint && !isCrouching)
        {
            StartSprint();
        }
        
        // 跳跃 (空格)
        if (Input.GetKeyDown(KeyCode.Space) && isGrounded)
        {
            Jump();
        }
    }

    /// <summary>
    /// 处理移动
    /// </summary>
    private void HandleMovement()
    {
        // 获取输入方向
        float horizontal = Input.GetAxis("Horizontal");
        float vertical = Input.GetAxis("Vertical");
        
        moveDirection = new Vector3(horizontal, 0, vertical);
        
        // 反身移动：移动时朝向移动方向
        if (moveDirection.magnitude > 0.1f)
        {
            isMoving = true;
            lastMoveDirection = moveDirection.normalized;
            
            // 平滑旋转朝向移动方向
            Quaternion targetRotation = Quaternion.LookRotation(lastMoveDirection);
            transform.rotation = Quaternion.Slerp(transform.rotation, targetRotation, Time.deltaTime * 15f);
        }
        else
        {
            isMoving = false;
        }
        
        // 计算当前速度
        float currentSpeed = GetCurrentSpeed();
        
        // 根据移动状态应用加速度或减速度
        if (moveDirection.magnitude > 0.1f)
        {
            // 加速
            velocity.x = Mathf.MoveTowards(velocity.x, moveDirection.x * currentSpeed, acceleration * Time.deltaTime);
            velocity.z = Mathf.MoveTowards(velocity.z, moveDirection.z * currentSpeed, acceleration * Time.deltaTime);
        }
        else
        {
            // 减速 (急停)
            velocity.x = Mathf.MoveTowards(velocity.x, 0f, deceleration * Time.deltaTime);
            velocity.z = Mathf.MoveTowards(velocity.z, 0f, deceleration * Time.deltaTime);
        }
    }

    /// <summary>
    /// 处理蹲下
    /// </summary>
    private void HandleCrouching()
    {
        // 平滑调整高度
        float targetHeight = isCrouching ? crouchHeight : standHeight;
        currentHeight = Mathf.MoveTowards(currentHeight, targetHeight, 10f * Time.deltaTime);
        
        // 更新相机和控制器高度
        if (playerCamera != null)
        {
            playerCamera.transform.localPosition = new Vector3(0, currentHeight - 1.6f, 0);
        }
    }

    /// <summary>
    /// 切换蹲下状态
    /// </summary>
    private void ToggleCrouch()
    {
        isCrouching = !isCrouching;
        
        // 蹲下时停止冲刺
        if (isCrouching && isSprinting)
        {
            StopSprint();
        }
    }

    /// <summary>
    /// 处理冲刺
    /// </summary>
    private void HandleSprinting()
    {
        if (isSprinting)
        {
            sprintTimer -= Time.deltaTime;
            
            // 冲刺时间结束
            if (sprintTimer <= 0)
            {
                StopSprint();
            }
        }
    }

    /// <summary>
    /// 开始冲刺
    /// </summary>
    private void StartSprint()
    {
        if (canSprint && !isCrouching && moveDirection.magnitude > 0.1f)
        {
            isSprinting = true;
            canSprint = false;
            sprintTimer = sprintDuration;
        }
    }

    /// <summary>
    /// 停止冲刺
    /// </summary>
    private void StopSprint()
    {
        isSprinting = false;
        
        // 设置冲刺冷却
        Invoke(nameof(ResetSprint), sprintCooldown);
    }

    /// <summary>
    /// 重置冲刺状态
    /// </summary>
    private void ResetSprint()
    {
        canSprint = true;
    }

    /// <summary>
    /// 获取当前速度
    /// </summary>
    private float GetCurrentSpeed()
    {
        if (isCrouching)
        {
            return crouchSpeed;
        }
        else if (isSprinting)
        {
            return sprintSpeed;
        }
        else
        {
            return walkSpeed;
        }
    }

    /// <summary>
    /// 应用重力
    /// </summary>
    private void ApplyGravity()
    {
        // 简单的重力模拟
        velocity.y -= 9.8f * Time.deltaTime;
    }

    /// <summary>
    /// 跳跃
    /// </summary>
    private void Jump()
    {
        if (isGrounded)
        {
            velocity.y = jumpForce;
            isGrounded = false;
        }
        else
        {
            // 空中跳跃 (二段跳效果)
            velocity.y = airJumpForce;
        }
    }

    /// <summary>
    /// 更新动画
    /// </summary>
    private void UpdateAnimator()
    {
        if (playerAnimator != null)
        {
            // 设置动画参数
            float speed = Mathf.Sqrt(velocity.x * velocity.x + velocity.z * velocity.z);
            playerAnimator.SetFloat("Speed", speed);
            playerAnimator.SetBool("IsAiming", isAiming);
            playerAnimator.SetBool("IsCrouching", isCrouching);
            playerAnimator.SetBool("IsSprinting", isSprinting);
        }
    }

    /// <summary>
    /// 应用移动
    /// </summary>
    private void FixedUpdate()
    {
        // 检测地面
        isGrounded = characterController.isGrounded;
        
        // 应用移动
        characterController.Move(velocity * Time.fixedDeltaTime);
    }

    /// <summary>
    /// 射击时的视角晃动
    /// </summary>
    public void ApplyRecoil()
    {
        if (isAiming && playerCamera != null)
        {
            // 简单的后坐力效果
            Vector3 recoilOffset = new Vector3(0, aimRecoil, 0);
            playerCamera.transform.localPosition += recoilOffset;
            
            // 恢复原位 (可以在射击后调用)
            Invoke(nameof(ResetCameraPosition), 0.1f);
        }
    }

    /// <summary>
    /// 重置相机位置
    /// </summary>
    private void ResetCameraPosition()
    {
        if (playerCamera != null)
        {
            playerCamera.transform.localPosition = new Vector3(0, currentHeight - 1.6f, 0);
        }
    }

    /// <summary>
    /// 检查是否可以开火 (急停射击)
    /// </summary>
    public bool CanShootAccurately()
    {
        // 如果玩家静止或速度很低，可以准确射击
        float speed = Mathf.Sqrt(velocity.x * velocity.x + velocity.z * velocity.z);
        return speed < 0.5f;
    }

    /// <summary>
    /// 获取玩家速度
    /// </summary>
    public float GetSpeed()
    {
        return Mathf.Sqrt(velocity.x * velocity.x + velocity.z * velocity.z);
    }

    /// <summary>
    /// 获取是否正在移动
    /// </summary>
    public bool IsMoving()
    {
        return isMoving;
    }
}
